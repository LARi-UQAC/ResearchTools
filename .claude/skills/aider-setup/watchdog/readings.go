package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// ticksPerSecond is the number of 100-nanosecond ticks in one second.
const ticksPerSecond = 10000000

type runner func(name string, args []string, timeout time.Duration) (string, error)
type getter func(url string, timeout time.Duration) ([]byte, error)

type procRow struct {
	PID        int
	ParentPID  int
	Name       string
	CPUSeconds float64
}

// Purpose: Parse the JSON output of Get-CimInstance Win32_Process into a list of procRow.
// Details: Accepts both a JSON array and a single JSON object. CPUSeconds is derived from KernelModeTime and UserModeTime.
// Inputs: text (string) - The JSON string to parse.
// Outputs: []procRow - The parsed process rows; error - If the text is not valid JSON of the expected shape.
// Raises: error if the input is not a JSON array or a single JSON object with the required fields.
func parseProcessTable(text string) ([]procRow, error) {
	// Try to parse as a list first
	var list []struct {
		ProcessId       int    `json:"ProcessId"`
		ParentProcessId int    `json:"ParentProcessId"`
		Name            string `json:"Name"`
		KernelModeTime  int64  `json:"KernelModeTime"`
		UserModeTime    int64  `json:"UserModeTime"`
	}
	if err := json.Unmarshal([]byte(text), &list); err == nil {
		rows := make([]procRow, 0, len(list))
		for _, item := range list {
			ticks := item.KernelModeTime + item.UserModeTime
			cpuSeconds := float64(ticks) / ticksPerSecond
			rows = append(rows, procRow{
				PID:        item.ProcessId,
				ParentPID:  item.ParentProcessId,
				Name:       item.Name,
				CPUSeconds: cpuSeconds,
			})
		}
		return rows, nil
	}

	// Try to parse as a single object
	var single struct {
		ProcessId       int    `json:"ProcessId"`
		ParentProcessId int    `json:"ParentProcessId"`
		Name            string `json:"Name"`
		KernelModeTime  int64  `json:"KernelModeTime"`
		UserModeTime    int64  `json:"UserModeTime"`
	}
	if err := json.Unmarshal([]byte(text), &single); err == nil {
		ticks := single.KernelModeTime + single.UserModeTime
		cpuSeconds := float64(ticks) / ticksPerSecond
		return []procRow{
			{
				PID:        single.ProcessId,
				ParentPID:  single.ParentProcessId,
				Name:       single.Name,
				CPUSeconds: cpuSeconds,
			},
		}, nil
	}

	// If both fail, return an error
	return nil, fmt.Errorf("failed to parse process table: not a list or single object")
}

// Purpose: Run the PowerShell command to retrieve the process table.
// Details: Executes a specific Get-CimInstance command via the injected runner.
// Inputs: run (runner) - The function to execute the command; timeout (time.Duration) - The timeout for the command.
// Outputs: []procRow - The parsed process table; error - If the command fails or output is unparseable.
// Raises: error if the runner fails or the output cannot be parsed.
func readProcessTable(run runner, timeout time.Duration) ([]procRow, error) {
	args := []string{
		"-Command",
		"Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,KernelModeTime,UserModeTime | ConvertTo-Json -Compress",
	}
	output, err := run("powershell", args, timeout)
	if err != nil {
		return nil, fmt.Errorf("failed to run powershell: %w", err)
	}
	return parseProcessTable(output)
}

// Purpose: Sum the CPU seconds of processes matching the given names.
// Details: Matching is case-insensitive and ignores the .exe extension.
// Inputs: rows ([]procRow) - The list of process rows; names ([]string) - The names to match against.
// Outputs: float64 - The total CPU seconds for matching processes.
// Raises: None.
func serverCPUSeconds(rows []procRow, names []string) float64 {
	var total float64
	for _, row := range rows {
		rowName := strings.ToLower(row.Name)
		if strings.HasSuffix(rowName, ".exe") {
			rowName = strings.TrimSuffix(rowName, ".exe")
		}
		for _, name := range names {
			name = strings.ToLower(name)
			if strings.HasSuffix(name, ".exe") {
				name = strings.TrimSuffix(name, ".exe")
			}
			if rowName == name {
				total += row.CPUSeconds
				break
			}
		}
	}
	return total
}

// Purpose: Read the GPU utilization percentage from nvidia-smi.
// Details: Returns the highest utilization value found in the output.
// Inputs: run (runner) - The function to execute nvidia-smi; timeout (time.Duration) - The timeout for the command.
// Outputs: float64 - The highest GPU utilization percentage; error - If the command fails or no valid number is found.
// Raises: error if nvidia-smi fails or returns no valid numbers.
func readGPUPercent(run runner, timeout time.Duration) (float64, error) {
	args := []string{
		"--query-gpu=utilization.gpu",
		"--format=csv,noheader,nounits",
	}
	output, err := run("nvidia-smi", args, timeout)
	if err != nil {
		return 0, fmt.Errorf("failed to run nvidia-smi: %w", err)
	}
	lines := strings.Split(strings.TrimSpace(output), "\n")
	var maxVal float64
	found := false
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		val, err := strconv.ParseFloat(line, 64)
		if err != nil {
			return 0, fmt.Errorf("failed to parse GPU utilization line %q: %w", line, err)
		}
		if !found || val > maxVal {
			maxVal = val
			found = true
		}
	}
	if !found {
		return 0, fmt.Errorf("nvidia-smi returned no valid GPU utilization numbers")
	}
	return maxVal, nil
}

// Purpose: Read the list of loaded models from the Ollama server.
// Details: Returns the name and context length of the first loaded model.
// Inputs: get (getter) - The function to perform the HTTP GET; url (string) - The base URL of the Ollama server; timeout (time.Duration) - The timeout for the request.
// Outputs: model (string) - The name of the first loaded model; contextLength (int) - Its context length; error - If the request fails or response is invalid.
// Raises: error if the HTTP request fails or the response cannot be parsed.
func readOllamaPS(get getter, url string, timeout time.Duration) (model string, contextLength int, err error) {
	psURL := url + "/api/ps"
	data, err := get(psURL, timeout)
	if err != nil {
		return "", 0, fmt.Errorf("failed to get ollama ps: %w", err)
	}
	var response struct {
		Models []struct {
			Name          string `json:"name"`
			ContextLength int    `json:"context_length"`
		} `json:"models"`
	}
	if err := json.Unmarshal(data, &response); err != nil {
		return "", 0, fmt.Errorf("failed to parse ollama ps response: %w", err)
	}
	if len(response.Models) == 0 {
		return "", 0, nil
	}
	return response.Models[0].Name, response.Models[0].ContextLength, nil
}

// Purpose: Read the state and plan from the run record file.
// Details: Parses the JSON file to extract the current state and plan name.
// Inputs: path (string) - The path to the run record file.
// Outputs: state (string) - The current state; plan (string) - The current plan; error - If the file is missing, unreadable, or invalid.
// Raises: error if the file cannot be read or parsed.
func readRunRecord(path string) (state, plan string, err error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", "", err
	}
	var record struct {
		State string `json:"state"`
		Plan  string `json:"plan"`
	}
	if err := json.Unmarshal(data, &record); err != nil {
		return "", "", err
	}
	return record.State, record.Plan, nil
}
