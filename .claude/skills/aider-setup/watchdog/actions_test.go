package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDescendantsExcludeTheWatchdogAndItsChildren(t *testing.T) {
	rows := []procRow{
		{PID: 1, ParentPID: 0, Name: "root", CPUSeconds: 10},
		{PID: 2, ParentPID: 1, Name: "child1", CPUSeconds: 5},
		{PID: 3, ParentPID: 2, Name: "grandchild", CPUSeconds: 2},
		{PID: 4, ParentPID: 1, Name: "watchdog", CPUSeconds: 1},
		{PID: 5, ParentPID: 4, Name: "watchdog-child", CPUSeconds: 1},
	}

	excluded := map[int]bool{4: true, 5: true}
	desc := descendantsOf(rows, 1, excluded)

	// Should contain 2 and 3, but not 4 and 5
	pids := make(map[int]bool)
	for _, r := range desc {
		pids[r.PID] = true
	}

	if !pids[2] || !pids[3] {
		t.Errorf("expected descendants 2 and 3, got %v", pids)
	}
	if pids[4] || pids[5] {
		t.Errorf("did not expect excluded pids 4 and 5, got %v", pids)
	}
}

func TestChildHoldingWorkIsTheDirectChildWithTheMostCPU(t *testing.T) {
	rows := []procRow{
		{PID: 1, ParentPID: 0, Name: "root", CPUSeconds: 10},
		{PID: 2, ParentPID: 1, Name: "low-cpu", CPUSeconds: 1},
		{PID: 3, ParentPID: 1, Name: "high-cpu", CPUSeconds: 5},
		{PID: 4, ParentPID: 3, Name: "high-cpu-child", CPUSeconds: 10}, // Adds to 3's total
	}

	excluded := map[int]bool{}
	child, found := childHoldingWork(rows, 1, excluded)
	if !found {
		t.Fatal("expected to find a child")
	}
	if child.PID != 3 {
		t.Errorf("expected pid 3, got %d", child.PID)
	}
}

func TestStopWorkReportsAProcessStillAlive(t *testing.T) {
	// Mock runner that returns a table where the target process is still present after kill
	runner := func(name string, args []string, timeout time.Duration) (string, error) {
		if name == "powershell" {
			// Return a table with PID 100 (child of 1)
			return `[{"ProcessId":100,"ParentProcessId":1,"Name":"work.exe","KernelModeTime":100,"UserModeTime":100}]`, nil
		}
		if name == "taskkill" {
			return "", nil // Success
		}
		return "", errors.New("unexpected command")
	}

	_, err := stopWork(runner, time.Second, 1, 999)
	if err == nil {
		t.Error("expected error because process is still alive")
	}
	if !strings.Contains(err.Error(), "still alive") {
		t.Errorf("expected 'still alive' in error, got %v", err)
	}
}

func TestStopWorkReportsAGoneProcess(t *testing.T) {
	// Mock runner that returns a table with process, then empty table after kill
	callCount := 0
	runner := func(name string, args []string, timeout time.Duration) (string, error) {
		if name == "powershell" {
			callCount++
			if callCount == 1 {
				return `[{"ProcessId":100,"ParentProcessId":1,"Name":"work.exe","KernelModeTime":100,"UserModeTime":100}]`, nil
			}
			return `[]`, nil // Empty table, process is gone
		}
		if name == "taskkill" {
			return "", nil
		}
		return "", errors.New("unexpected command")
	}

	ok, err := stopWork(runner, time.Second, 1, 999)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !ok {
		t.Error("expected success")
	}
}

func TestPathOutsideTheLogsFolderIsRefused(t *testing.T) {
	dir := t.TempDir()
	_, err := resolveInside(dir, "../secret.txt")
	if err == nil {
		t.Error("expected error for path traversal")
	}
}

func TestAppendStopLineWritesOneJSONLine(t *testing.T) {
	dir := t.TempDir()
	r := reading{
		Model:      "test-model",
		CPUPercent: 10.5,
		GPUPercent: ptr(20.5),
		Plan:       "plan4.md",
	}
	at := time.Date(2026, 11, 10, 12, 0, 0, 0, time.UTC)

	err := appendStopLine(dir, at, r)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	path := filepath.Join(dir, "watchdog.log")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read log: %v", err)
	}

	var entry map[string]interface{}
	if err := json.Unmarshal(data, &entry); err != nil {
		t.Fatalf("failed to parse log entry: %v", err)
	}

	if entry["event"] != "stop" {
		t.Errorf("expected event 'stop', got %v", entry["event"])
	}
	if entry["model"] != "test-model" {
		t.Errorf("expected model 'test-model', got %v", entry["model"])
	}
}

func TestWriteStopSignalNamesThePlan(t *testing.T) {
	dir := t.TempDir()
	plan := "plan4.md"

	err := writeStopSignal(dir, plan)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	path := filepath.Join(dir, "watchdog-stop.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read signal: %v", err)
	}

	var entry map[string]string
	if err := json.Unmarshal(data, &entry); err != nil {
		t.Fatalf("failed to parse signal: %v", err)
	}

	if entry["plan"] != plan {
		t.Errorf("expected plan %q, got %q", plan, entry["plan"])
	}
}

func TestAppendStopLineFailsIfLogsDirIsAFile(t *testing.T) {
	dir := t.TempDir()
	filePath := filepath.Join(dir, "blocker")
	if err := os.WriteFile(filePath, []byte("blocker"), 0644); err != nil {
		t.Fatalf("failed to create blocker file: %v", err)
	}

	r := reading{
		Model:      "test-model",
		CPUPercent: 10.5,
		GPUPercent: ptr(20.5),
		Plan:       "plan4.md",
	}
	at := time.Date(2026, 11, 10, 12, 0, 0, 0, time.UTC)

	err := appendStopLine(filePath, at, r)
	if err == nil {
		t.Error("expected error when logsDir is a file, got nil")
	}
}

func TestWriteStopSignalFailsIfLogsDirIsAFile(t *testing.T) {
	dir := t.TempDir()
	filePath := filepath.Join(dir, "blocker")
	if err := os.WriteFile(filePath, []byte("blocker"), 0644); err != nil {
		t.Fatalf("failed to create blocker file: %v", err)
	}

	err := writeStopSignal(filePath, "plan4.md")
	if err == nil {
		t.Error("expected error when logsDir is a file, got nil")
	}
}
