package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadSettingsNamesTheMissingKeyAndFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	content := `{
		"pollSeconds": {
			"value": 30,
			"provenance": "test"
		}
	}`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	_, err := loadSettings(path)
	if err == nil {
		t.Fatal("expected error for missing key, got nil")
	}
	expected := `missing key "negligibleReferencePercent" in settings file ` + path
	if err.Error() != expected {
		t.Errorf("expected error %q, got %q", expected, err.Error())
	}
}

func TestLoadSettingsRefusesAnEntryWithoutProvenance(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	content := `{
		"pollSeconds": {
			"value": 30,
			"provenance": ""
		}
	}`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	_, err := loadSettings(path)
	if err == nil {
		t.Fatal("expected error for empty provenance, got nil")
	}
	expected := `empty provenance for key "pollSeconds" in settings file ` + path
	if err.Error() != expected {
		t.Errorf("expected error %q, got %q", expected, err.Error())
	}
}

func TestShippedSettingsLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	content := `{
		"pollSeconds": {
			"value": 30,
			"provenance": "initial value, adjust after measuring"
		},
		"negligibleReferencePercent": {
			"value": 5,
			"provenance": "initial value, adjust after measuring"
		},
		"lowReadings": {
			"value": 6,
			"provenance": "initial value, adjust after measuring"
		},
		"watchedStates": {
			"value": [
				"writing",
				"auditing"
			],
			"provenance": "fixed list"
		},
		"terminalStates": {
			"value": [
				"done",
				"done_with_blocked",
				"failed"
			],
			"provenance": "fixed list"
		},
		"modelServerNames": {
			"value": [
				"ollama",
				"llama-server"
			],
			"provenance": "fixed list"
		},
		"ollamaURL": {
			"value": "http://127.0.0.1:11434",
			"provenance": "fixed list"
		},
		"callTimeoutSeconds": {
			"value": 30,
			"provenance": "initial value, adjust after measuring"
		},
		"sampleSeconds": {"value": 2, "provenance": "test"},
		"prompt": {"value": "Write one paragraph.", "provenance": "test"},
		"numPredict": {"value": 256, "provenance": "test"},
		"warmupNumPredict": {"value": 8, "provenance": "test"},
		"generationTimeoutSeconds": {"value": 600, "provenance": "test"}
	}`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	s, err := loadSettings(path)
	if err != nil {
		t.Fatalf("failed to load shipped settings: %v", err)
	}

	if s.PollSeconds != 30 {
		t.Errorf("expected PollSeconds 30, got %d", s.PollSeconds)
	}
	if s.NegligibleReferencePercent != 5 {
		t.Errorf("expected NegligibleReferencePercent 5, got %f", s.NegligibleReferencePercent)
	}
	if s.LowReadings != 6 {
		t.Errorf("expected LowReadings 6, got %d", s.LowReadings)
	}
	if len(s.WatchedStates) != 2 || s.WatchedStates[0] != "writing" || s.WatchedStates[1] != "auditing" {
		t.Errorf("unexpected WatchedStates: %v", s.WatchedStates)
	}
	if len(s.TerminalStates) != 3 || s.TerminalStates[0] != "done" || s.TerminalStates[1] != "done_with_blocked" || s.TerminalStates[2] != "failed" {
		t.Errorf("unexpected TerminalStates: %v", s.TerminalStates)
	}
	if len(s.ModelServerNames) != 2 || s.ModelServerNames[0] != "ollama" || s.ModelServerNames[1] != "llama-server" {
		t.Errorf("unexpected ModelServerNames: %v", s.ModelServerNames)
	}
	if s.OllamaURL != "http://127.0.0.1:11434" {
		t.Errorf("unexpected OllamaURL: %s", s.OllamaURL)
	}
	if s.CallTimeoutSeconds != 30 {
		t.Errorf("expected CallTimeoutSeconds 30, got %d", s.CallTimeoutSeconds)
	}
}

func TestLoadReferencesReadsTheMeasuredEntry(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "refs.json")
	content := `{
		"models": {
			"test-model": {
				"reference_decode": {
					"num_ctx": 4096,
					"cpu_percent": {
						"median": 50.5,
						"min": 10.0
					},
					"gpu_percent": {
						"median": 80.0,
						"min": 20.0
					}
				}
			}
		}
	}`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	refs, err := loadReferences(path)
	if err != nil {
		t.Fatalf("failed to load references: %v", err)
	}

	ref, ok := refs["test-model"]
	if !ok {
		t.Fatal("expected test-model in references")
	}
	if ref.NumCtx != 4096 {
		t.Errorf("expected NumCtx 4096, got %d", ref.NumCtx)
	}
	if ref.CPU.Median != 50.5 {
		t.Errorf("expected CPU Median 50.5, got %f", ref.CPU.Median)
	}
	if ref.CPU.Min != 10.0 {
		t.Errorf("expected CPU Min 10.0, got %f", ref.CPU.Min)
	}
	if ref.GPU.Median != 80.0 {
		t.Errorf("expected GPU Median 80.0, got %f", ref.GPU.Median)
	}
	if ref.GPU.Min != 20.0 {
		t.Errorf("expected GPU Min 20.0, got %f", ref.GPU.Min)
	}
}

func TestLoadReferencesMissingFileIsEmpty(t *testing.T) {
	path := "nonexistent-refs.json"
	refs, err := loadReferences(path)
	if err != nil {
		t.Fatalf("expected no error for missing file, got %v", err)
	}
	if len(refs) != 0 {
		t.Errorf("expected empty map, got %v", refs)
	}
}

func TestLoadReferencesRefusesInvalidJSON(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "refs.json")
	content := `{ invalid json`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file: %v", err)
	}

	_, err := loadReferences(path)
	if err == nil {
		t.Fatal("expected error for invalid JSON, got nil")
	}
}

func TestLoadReferencesUnreadableFileIsAnError(t *testing.T) {
	// Using a directory path ensures os.ReadFile fails on all platforms,
	// avoiding platform-specific permission issues (e.g. Windows admin bypass).
	path := t.TempDir()

	_, err := loadReferences(path)
	if err == nil {
		t.Fatal("expected error for unreadable file (directory), got nil")
	}
}
