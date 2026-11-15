package main

import (
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

func TestParseProcessTableAcceptsAListAndASingleObject(t *testing.T) {
	listJSON := `[{"ProcessId":123,"ParentProcessId":456,"Name":"test.exe","KernelModeTime":100,"UserModeTime":200}]`
	rows, err := parseProcessTable(listJSON)
	if err != nil {
		t.Fatalf("expected no error for list, got %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("expected 1 row, got %d", len(rows))
	}
	if rows[0].PID != 123 {
		t.Errorf("expected PID 123, got %d", rows[0].PID)
	}
	if rows[0].ParentPID != 456 {
		t.Errorf("expected ParentPID 456, got %d", rows[0].ParentPID)
	}
	if rows[0].Name != "test.exe" {
		t.Errorf("expected Name test.exe, got %s", rows[0].Name)
	}

	singleJSON := `{"ProcessId":123,"ParentProcessId":456,"Name":"test.exe","KernelModeTime":100,"UserModeTime":200}`
	rows, err = parseProcessTable(singleJSON)
	if err != nil {
		t.Fatalf("expected no error for single object, got %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("expected 1 row, got %d", len(rows))
	}
	if rows[0].PID != 123 {
		t.Errorf("expected PID 123, got %d", rows[0].PID)
	}
}

func TestCPUSecondsComeFromKernelPlusUserTicks(t *testing.T) {
	// 100000000 ticks = 10 seconds (100000000 / 10000000)
	// Kernel: 50000000, User: 50000000 -> Total: 10 seconds
	json := `[{"ProcessId":123,"ParentProcessId":456,"Name":"test.exe","KernelModeTime":50000000,"UserModeTime":50000000}]`
	rows, err := parseProcessTable(json)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("expected 1 row, got %d", len(rows))
	}
	if rows[0].CPUSeconds != 10.0 {
		t.Errorf("expected CPUSeconds 10.0, got %f", rows[0].CPUSeconds)
	}
}

func TestTextThatIsNotATableIsRefused(t *testing.T) {
	// JSON that is not a list or an object should be refused.
	numJSON := `123`
	_, err := parseProcessTable(numJSON)
	if err == nil {
		t.Error("expected error for non-object JSON, got nil")
	}
}

func TestServerCPUSecondsMatchesNamesWithoutExe(t *testing.T) {
	rows := []procRow{
		{PID: 1, ParentPID: 0, Name: "ollama.exe", CPUSeconds: 10.0},
		{PID: 2, ParentPID: 0, Name: "other.exe", CPUSeconds: 5.0},
		{PID: 3, ParentPID: 0, Name: "OLLAMA", CPUSeconds: 2.0}, // Case insensitive
	}
	names := []string{"ollama"}
	// Should match "ollama.exe" and "OLLAMA"
	// 10.0 + 2.0 = 12.0
	cpuSeconds := serverCPUSeconds(rows, names)
	if cpuSeconds != 12.0 {
		t.Errorf("expected CPUSeconds 12.0, got %f", cpuSeconds)
	}
}

func TestGPUPercentIsTheHighestLine(t *testing.T) {
	// Mock runner
	runner := func(name string, args []string, timeout time.Duration) (string, error) {
		if name != "nvidia-smi" {
			return "", errors.New("unexpected program")
		}
		return "45\n90\n10", nil
	}
	gpuPercent, err := readGPUPercent(runner, time.Second)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if gpuPercent != 90 {
		t.Errorf("expected GPU percent 90, got %f", gpuPercent)
	}
}

func TestMissingNvidiaSmiGivesError(t *testing.T) {
	runner := func(name string, args []string, timeout time.Duration) (string, error) {
		return "", errors.New("not found")
	}
	_, err := readGPUPercent(runner, time.Second)
	if err == nil {
		t.Error("expected error for missing nvidia-smi, got nil")
	}
}

func TestReadOllamaPSReturnsModelAndContext(t *testing.T) {
	getter := func(url string, timeout time.Duration) ([]byte, error) {
		if !strings.HasSuffix(url, "/api/ps") {
			return nil, errors.New("unexpected url")
		}
		return []byte(`{"models":[{"name":"test-model","context_length":4096}]}`), nil
	}
	model, contextLength, err := readOllamaPS(getter, "http://localhost:11434", time.Second)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if model != "test-model" {
		t.Errorf("expected model test-model, got %s", model)
	}
	if contextLength != 4096 {
		t.Errorf("expected context length 4096, got %d", contextLength)
	}
}

func TestNoLoadedModelGivesAnEmptyModel(t *testing.T) {
	getter := func(url string, timeout time.Duration) ([]byte, error) {
		return []byte(`{"models":[]}`), nil
	}
	model, contextLength, err := readOllamaPS(getter, "http://localhost:11434", time.Second)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if model != "" {
		t.Errorf("expected empty model, got %s", model)
	}
	if contextLength != 0 {
		t.Errorf("expected context length 0, got %d", contextLength)
	}
}

func TestCorruptRunRecordReturnsError(t *testing.T) {
	dir := t.TempDir()
	path := dir + `/run_record.json`
	content := `{ invalid json`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}
	_, _, err := readRunRecord(path)
	if err == nil {
		t.Error("expected error for corrupt run record, got nil")
	}
}

func TestReadRunRecordMissingFileReturnsError(t *testing.T) {
	_, _, err := readRunRecord("nonexistent_file.json")
	if err == nil {
		t.Error("expected error for missing run record, got nil")
	}
}

func TestReadOllamaPSFailsOnError(t *testing.T) {
	getter := func(url string, timeout time.Duration) ([]byte, error) {
		return nil, errors.New("network error")
	}
	_, _, err := readOllamaPS(getter, "http://localhost:11434", time.Second)
	if err == nil {
		t.Error("expected error for failed ollama ps request, got nil")
	}
}

func TestReadOllamaPSRefusesNonJSON(t *testing.T) {
	getter := func(url string, timeout time.Duration) ([]byte, error) {
		return []byte(`not json`), nil
	}
	_, _, err := readOllamaPS(getter, "http://localhost:11434", time.Second)
	if err == nil {
		t.Error("expected error for non-JSON ollama ps response, got nil")
	}
}
