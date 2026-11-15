package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Purpose: Find all descendants of a root PID in the process table.
// Details: Excludes the root PID itself and any PIDs in the excluded set, along with their subtrees.
// Inputs: rows ([]procRow) - The process table; rootPID (int) - The root process ID; excluded (map[int]bool) - PIDs to exclude.
// Outputs: []procRow - The list of descendant process rows.
// Raises: None.
func descendantsOf(rows []procRow, rootPID int, excluded map[int]bool) []procRow {
	// Build a map of parent to children for efficient lookup
	children := make(map[int][]procRow)
	for _, row := range rows {
		children[row.ParentPID] = append(children[row.ParentPID], row)
	}

	var result []procRow
	var visit func(pid int)
	visit = func(pid int) {
		if excluded[pid] {
			return
		}
		for _, child := range children[pid] {
			if child.PID == rootPID {
				continue
			}
			if excluded[child.PID] {
				continue
			}
			result = append(result, child)
			visit(child.PID)
		}
	}
	visit(rootPID)
	return result
}

// Purpose: Identify the direct child of the root PID that holds the most work (CPU seconds).
// Details: Considers the subtree CPU sum for each direct child. Excludes watchdog and its children.
// Inputs: rows ([]procRow) - The process table; rootPID (int) - The parent process ID; excluded (map[int]bool) - PIDs to exclude.
// Outputs: (procRow, bool) - The child row with the highest subtree CPU, and true if found.
// Raises: None.
func childHoldingWork(rows []procRow, rootPID int, excluded map[int]bool) (procRow, bool) {
	var best procRow
	bestCPU := 0.0
	found := false

	// Get direct children
	directChildren := make([]procRow, 0)
	for _, row := range rows {
		if row.ParentPID == rootPID && !excluded[row.PID] {
			directChildren = append(directChildren, row)
		}
	}

	for _, child := range directChildren {
		// Calculate total CPU for this child's subtree
		subtree := descendantsOf(rows, child.PID, excluded)
		totalCPU := child.CPUSeconds
		for _, desc := range subtree {
			totalCPU += desc.CPUSeconds
		}

		if !found || totalCPU > bestCPU {
			best = child
			bestCPU = totalCPU
			found = true
		}
	}

	return best, found
}

// Purpose: Stop the work-holding child process and verify it is gone.
// Details: Uses taskkill to force terminate the process tree. Checks if the PID is still present in the table.
// Inputs: run (runner) - Function to execute commands; timeout (time.Duration) - Command timeout; parentPID (int) - Parent PID; selfPID (int) - Watchdog PID.
// Outputs: (bool, error) - True if the process was successfully stopped (gone), error if anything failed.
// Raises: error if taskkill fails or if the process is still alive after stopping.
func stopWork(run runner, timeout time.Duration, parentPID, selfPID int) (bool, error) {
	// Read initial table
	rows, err := readProcessTable(run, timeout)
	if err != nil {
		return false, fmt.Errorf("failed to read process table: %w", err)
	}

	excluded := map[int]bool{selfPID: true}
	child, found := childHoldingWork(rows, parentPID, excluded)
	if !found {
		// No work-holding child found, nothing to stop
		return true, nil
	}

	// Execute taskkill
	args := []string{"/PID", fmt.Sprintf("%d", child.PID), "/T", "/F"}
	_, err = run("taskkill", args, timeout)
	if err != nil {
		return false, fmt.Errorf("failed to kill process %d: %w", child.PID, err)
	}

	// Verify it is gone
	rowsAfter, err := readProcessTable(run, timeout)
	if err != nil {
		return false, fmt.Errorf("failed to read process table after kill: %w", err)
	}

	for _, row := range rowsAfter {
		if row.PID == child.PID {
			return false, fmt.Errorf("process %d is still alive after stop attempt", child.PID)
		}
	}

	return true, nil
}

// Purpose: Resolve a filename to a path inside the logs directory, refusing if it escapes.
// Details: Ensures the resolved path is strictly inside the logsDir.
// Inputs: logsDir (string) - The base directory; name (string) - The file name or relative path.
// Outputs: (string, error) - The resolved absolute path, or an error if it escapes logsDir.
// Raises: error if the resolved path is not inside logsDir.
func resolveInside(logsDir, name string) (string, error) {
	absLogsDir, err := filepath.Abs(logsDir)
	if err != nil {
		return "", fmt.Errorf("failed to resolve logs dir: %w", err)
	}

	// Clean the name to prevent traversal
	cleanName := filepath.Clean(name)
	absPath := filepath.Join(absLogsDir, cleanName)

	// Ensure it starts with absLogsDir
	if !strings.HasPrefix(absPath, absLogsDir+string(os.PathSeparator)) && absPath != absLogsDir {
		return "", fmt.Errorf("path %s escapes logs directory %s", name, logsDir)
	}

	return absPath, nil
}

// Purpose: Append a JSON line to the watchdog log file.
// Details: Writes time, event, model, cpu_percent, gpu_percent, plan.
// Inputs: logsDir (string) - Directory for the log file; at (time.Time) - Timestamp; r (reading) - The reading data.
// Outputs: error - If writing fails.
// Raises: error if the file cannot be opened or written to.
func appendStopLine(logsDir string, at time.Time, r reading) error {
	path, err := resolveInside(logsDir, "watchdog.log")
	if err != nil {
		return err
	}

	entry := map[string]interface{}{
		"time":        at.Format(time.RFC3339),
		"event":       "stop",
		"model":       r.Model,
		"cpu_percent": r.CPUPercent,
		"gpu_percent": r.GPUPercent,
		"plan":        r.Plan,
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("failed to marshal log entry: %w", err)
	}
	data = append(data, '\n')

	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file: %w", err)
	}
	defer file.Close()

	if _, err := file.Write(data); err != nil {
		return fmt.Errorf("failed to write log entry: %w", err)
	}

	return nil
}

// Purpose: Append a JSON line to the watchdog log for a failed step or for the end of the watch.
// Details: Writes time, event ("error" or "gave_up"), step, detail and the count of failures in a row.
// Inputs: logsDir (string) - Directory for the log file; at (time.Time) - Timestamp; event, step, detail (string) - What happened; failures (int) - Failures in a row.
// Outputs: error - If writing fails.
// Raises: error if the file cannot be opened or written to.
func appendEventLine(logsDir string, at time.Time, event, step, detail string, failures int) error {
	path, err := resolveInside(logsDir, "watchdog.log")
	if err != nil {
		return err
	}

	data, err := json.Marshal(map[string]interface{}{
		"time":     at.Format(time.RFC3339),
		"event":    event,
		"step":     step,
		"detail":   detail,
		"failures": failures,
	})
	if err != nil {
		return fmt.Errorf("failed to marshal log entry: %w", err)
	}
	data = append(data, '\n')

	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file: %w", err)
	}
	defer file.Close()

	if _, err := file.Write(data); err != nil {
		return fmt.Errorf("failed to write log entry: %w", err)
	}
	return nil
}

// Purpose: Write the stop signal file with the plan name.
// Details: Creates a JSON file named watchdog-stop.json containing the plan.
// Inputs: logsDir (string) - Directory for the signal file; plan (string) - The plan name.
// Outputs: error - If writing fails.
// Raises: error if the file cannot be created or written to.
func writeStopSignal(logsDir, plan string) error {
	path, err := resolveInside(logsDir, "watchdog-stop.json")
	if err != nil {
		return err
	}

	entry := map[string]string{
		"plan": plan,
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("failed to marshal stop signal: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write stop signal: %w", err)
	}

	return nil
}
