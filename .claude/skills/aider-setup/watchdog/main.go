package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"time"
)

type deps struct {
	runner func(name string, args []string, timeout time.Duration) (string, error)
	getter func(url string, timeout time.Duration) ([]byte, error)
	now    func() time.Time
	sleep  func(time.Duration)
}

type watchOptions struct {
	ParentPID     int
	RunRecord     string
	LogsDir       string
	Settings      settings
	References    map[string]reference
	MaxIterations int
}

// Purpose: Run the watch loop.
// Inputs: opts - watch options, d - dependencies (runner, getter, clock, sleep).
// Outputs: int - exit code (0 success, non-zero failure).
func watch(opts watchOptions, d deps) int {
	tracker := newTracker(opts.References, opts.Settings)
	var lastCPUSeconds float64
	var lastTime time.Time
	firstPoll := true
	iterations := 0
	failures := 0

	// A failed read or stop skips this tour. Only a run of failures with no success in between ends the
	// watch, and each failure and the final exit leave a line in watchdog.log, so a death is never silent.
	// Measured 2026-11-13 (night un5b): one failed call ended the process with exit 1 and no trace, and
	// the run went on for hours with no watchdog.
	skip := func(step string, cause error) bool {
		failures++
		_ = appendEventLine(opts.LogsDir, d.now(), "error", step, cause.Error(), failures)
		if failures >= opts.Settings.MaxConsecutiveFailures {
			_ = appendEventLine(opts.LogsDir, d.now(), "gave_up", step, cause.Error(), failures)
			return true
		}
		return false
	}
	pause := time.Duration(opts.Settings.PollSeconds) * time.Second

	for {
		if opts.MaxIterations > 0 && iterations >= opts.MaxIterations {
			return 0
		}
		iterations++
		now := d.now()

		// 1. Check if parent is gone
		rows, err := readProcessTable(d.runner, time.Duration(opts.Settings.CallTimeoutSeconds)*time.Second)
		if err != nil {
			if skip("process table", err) {
				return 1
			}
			d.sleep(pause)
			continue
		}

		parentAlive := false
		for _, row := range rows {
			if row.PID == opts.ParentPID {
				parentAlive = true
				break
			}
		}
		if !parentAlive {
			return 0
		}

		// 2. Check run record state
		state, plan, err := readRunRecord(opts.RunRecord)
		if err != nil {
			// The driver rewrites the record through a temporary file, so a read can fall on the swap.
			if skip("run record", err) {
				return 1
			}
			d.sleep(pause)
			continue
		}

		if contains(opts.Settings.TerminalStates, state) {
			return 0
		}

		// 3. Read model and GPU
		model, contextLength, err := readOllamaPS(d.getter, opts.Settings.OllamaURL, time.Duration(opts.Settings.CallTimeoutSeconds)*time.Second)
		if err != nil {
			// A model server saturating the CPU can miss the call timeout once without being down.
			if skip("ollama", err) {
				return 1
			}
			d.sleep(pause)
			continue
		}

		gpuPercent, err := readGPUPercent(d.runner, time.Duration(opts.Settings.CallTimeoutSeconds)*time.Second)
		var gpuPtr *float64
		if err == nil {
			gpuPtr = &gpuPercent
		}

		// 4. Calculate CPU percent
		cpuSeconds := serverCPUSeconds(rows, opts.Settings.ModelServerNames)
		var cpuPercent float64
		if !firstPoll {
			elapsed := now.Sub(lastTime).Seconds()
			if elapsed > 0 {
				cpuPercent = (cpuSeconds - lastCPUSeconds) / elapsed * 100
			}
		}
		firstPoll = false
		lastCPUSeconds = cpuSeconds
		lastTime = now

		// 5. Build reading
		r := reading{
			Model:         model,
			CPUPercent:    cpuPercent,
			GPUPercent:    gpuPtr,
			ContextLength: contextLength,
			State:         state,
			Plan:          plan,
		}

		// 6. Update tracker
		stalled := tracker.update(r)
		if stalled {
			// Stop work
			selfPID := os.Getpid()
			stopped, err := stopWork(d.runner, time.Duration(opts.Settings.CallTimeoutSeconds)*time.Second, opts.ParentPID, selfPID)
			if err == nil && !stopped {
				err = fmt.Errorf("the process is still alive after the stop")
			}
			if err == nil {
				err = appendStopLine(opts.LogsDir, d.now(), r)
			}
			if err == nil {
				err = writeStopSignal(opts.LogsDir, plan)
			}
			if err != nil {
				// The tracker is kept: the next tour tries the stop again.
				if skip("stop", err) {
					return 1
				}
				d.sleep(pause)
				continue
			}

			// Reset tracker
			tracker = newTracker(opts.References, opts.Settings)
		}

		// 7. A whole tour went through: the failure count starts again. Then sleep.
		failures = 0
		d.sleep(pause)
	}
}

// Purpose: Parse command line arguments and run the watch command.
// Inputs: args - os.Args[1:].
// Outputs: int - exit code.
func runWatchCommand(args []string) int {
	if len(args) < 1 || args[0] != "watch" {
		fmt.Fprintln(os.Stderr, `{"error": "unknown command"}`)
		return 2
	}

	// Parse flags
	// --driver-pid N --run-record PATH --logs-dir DIR --settings FILE --reference FILE
	var parentPID int
	var runRecord, logsDir, settingsFile, referenceFile string
	var maxIterations int

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--driver-pid":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --driver-pid"}`)
				return 2
			}
			i++
			fmt.Sscanf(args[i], "%d", &parentPID)
		case "--run-record":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --run-record"}`)
				return 2
			}
			i++
			runRecord = args[i]
		case "--logs-dir":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --logs-dir"}`)
				return 2
			}
			i++
			logsDir = args[i]
		case "--settings":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --settings"}`)
				return 2
			}
			i++
			settingsFile = args[i]
		case "--reference":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --reference"}`)
				return 2
			}
			i++
			referenceFile = args[i]
		case "--max-iterations":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --max-iterations"}`)
				return 2
			}
			i++
			fmt.Sscanf(args[i], "%d", &maxIterations)
		default:
			fmt.Fprintf(os.Stderr, `{"error": "unknown argument %s"}`, args[i])
			return 2
		}
	}

	if parentPID == 0 || runRecord == "" || logsDir == "" || settingsFile == "" || referenceFile == "" {
		fmt.Fprintln(os.Stderr, `{"error": "missing required arguments"}`)
		return 2
	}

	s, err := loadSettings(settingsFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, `{"error": "%s"}`, err.Error())
		return 2
	}

	refs, err := loadReferences(referenceFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, `{"error": "%s"}`, err.Error())
		return 2
	}

	opts := watchOptions{
		ParentPID:     parentPID,
		RunRecord:     runRecord,
		LogsDir:       logsDir,
		Settings:      s,
		References:    refs,
		MaxIterations: maxIterations,
	}

	d := deps{
		runner: func(name string, args []string, timeout time.Duration) (string, error) {
			return runCommand(name, args, timeout)
		},
		getter: func(url string, timeout time.Duration) ([]byte, error) {
			return httpGet(url, timeout)
		},
		now:   time.Now,
		sleep: time.Sleep,
	}

	return watch(opts, d)
}

// runCommand runs a command with a timeout and returns its stdout.
func runCommand(name string, args []string, timeout time.Duration) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, name, args...)
	output, err := cmd.Output()
	if err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return "", fmt.Errorf("command %s timed out after %s", name, timeout)
		}
		return "", err
	}
	return string(output), nil
}

// httpGet performs an HTTP GET request with a timeout.
func httpGet(url string, timeout time.Duration) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s returned status %d", url, resp.StatusCode)
	}

	buf := new(bytes.Buffer)
	if _, err := buf.ReadFrom(resp.Body); err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, `{"error": "missing command"}`)
		os.Exit(2)
	}

	switch args[0] {
	case "watch":
		code := runWatchCommand(args)
		os.Exit(code)
	case "reference":
		code := runReferenceCommand(args)
		os.Exit(code)
	default:
		fmt.Fprintf(os.Stderr, `{"error": "unknown command %s"}`, args[0])
		os.Exit(2)
	}
}

// Purpose: Run the reference command.
// Inputs: args - os.Args[1:].
// Outputs: int - exit code.
func runReferenceCommand(args []string) int {
	if len(args) < 1 || args[0] != "reference" {
		fmt.Fprintln(os.Stderr, `{"error": "unknown command"}`)
		return 2
	}

	var tag, settingsFile, referenceFile string
	var dryRun bool

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--tag":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --tag"}`)
				return 2
			}
			i++
			tag = args[i]
		case "--settings":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --settings"}`)
				return 2
			}
			i++
			settingsFile = args[i]
		case "--reference":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, `{"error": "missing value for --reference"}`)
				return 2
			}
			i++
			referenceFile = args[i]
		case "--dry-run":
			dryRun = true
		default:
			fmt.Fprintf(os.Stderr, `{"error": "unknown argument %s"}`, args[i])
			return 2
		}
	}

	if tag == "" || settingsFile == "" || referenceFile == "" {
		fmt.Fprintln(os.Stderr, `{"error": "missing required arguments"}`)
		return 2
	}

	s, err := loadSettings(settingsFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, `{"error": "%s"}`, err.Error())
		return 2
	}

	if dryRun {
		fmt.Println("Dry run: would measure reference for", tag)
		return 0
	}

	d := refDeps{
		runner: func(name string, args []string, timeout time.Duration) (string, error) {
			return runCommand(name, args, timeout)
		},
		getter: func(url string, timeout time.Duration) ([]byte, error) {
			return httpGet(url, timeout)
		},
		post: func(url string, body []byte, timeout time.Duration) ([]byte, error) {
			return httpPost(url, body, timeout)
		},
		now:   time.Now,
		sleep: time.Sleep,
	}

	rec, err := measureReference(d, tag, s)
	if err != nil {
		fmt.Fprintf(os.Stderr, `{"error": "%s"}`, err.Error())
		return 1
	}

	if err := writeReference(referenceFile, tag, rec); err != nil {
		fmt.Fprintf(os.Stderr, `{"error": "%s"}`, err.Error())
		return 1
	}

	// Print one JSON line with the record
	out, _ := json.Marshal(rec)
	fmt.Println(string(out))

	return 0
}

// httpPost performs an HTTP POST request with a timeout.
func httpPost(url string, body []byte, timeout time.Duration) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("POST %s returned status %d", url, resp.StatusCode)
	}

	buf := new(bytes.Buffer)
	if _, err := buf.ReadFrom(resp.Body); err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}
