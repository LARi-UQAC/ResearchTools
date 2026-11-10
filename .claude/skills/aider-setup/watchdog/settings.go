package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// settings holds the configuration values for the watchdog.
type settings struct {
	PollSeconds                int
	NegligibleReferencePercent float64
	LowReadings                int
	WatchedStates              []string
	TerminalStates             []string
	ModelServerNames           []string
	OllamaURL                  string
	CallTimeoutSeconds         int
	SampleSeconds              int
	Prompt                     string
	NumPredict                 int
	WarmupNumPredict           int
	GenerationTimeoutSeconds   int
}

// Purpose: Load and validate the watchdog settings from a JSON file.
// Details: Each key in the JSON file must be an object with "value" and "provenance".
// Inputs: path - the file system path to the settings JSON file.
// Outputs: settings - the parsed configuration struct.
// Raises: error if the file is missing, invalid JSON, missing keys, or has empty provenance.
func loadSettings(path string) (settings, error) {
	var s settings
	data, err := os.ReadFile(path)
	if err != nil {
		return s, fmt.Errorf("failed to read settings file %s: %w", path, err)
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return s, fmt.Errorf("failed to parse settings file %s: %w", path, err)
	}

	keys := []string{
		"pollSeconds",
		"negligibleReferencePercent",
		"lowReadings",
		"watchedStates",
		"terminalStates",
		"modelServerNames",
		"ollamaURL",
		"callTimeoutSeconds",
		"sampleSeconds",
		"prompt",
		"numPredict",
		"warmupNumPredict",
		"generationTimeoutSeconds",
	}

	for _, key := range keys {
		rawVal, ok := raw[key]
		if !ok {
			return s, fmt.Errorf("missing key %q in settings file %s", key, path)
		}

		var entry struct {
			Value      json.RawMessage `json:"value"`
			Provenance string          `json:"provenance"`
		}
		if err := json.Unmarshal(rawVal, &entry); err != nil {
			return s, fmt.Errorf("failed to parse entry for key %q in settings file %s: %w", key, path, err)
		}

		if entry.Provenance == "" {
			return s, fmt.Errorf("empty provenance for key %q in settings file %s", key, path)
		}

		switch key {
		case "pollSeconds":
			if err := json.Unmarshal(entry.Value, &s.PollSeconds); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "negligibleReferencePercent":
			if err := json.Unmarshal(entry.Value, &s.NegligibleReferencePercent); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "lowReadings":
			if err := json.Unmarshal(entry.Value, &s.LowReadings); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "watchedStates":
			if err := json.Unmarshal(entry.Value, &s.WatchedStates); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "terminalStates":
			if err := json.Unmarshal(entry.Value, &s.TerminalStates); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "modelServerNames":
			if err := json.Unmarshal(entry.Value, &s.ModelServerNames); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "ollamaURL":
			if err := json.Unmarshal(entry.Value, &s.OllamaURL); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "callTimeoutSeconds":
			if err := json.Unmarshal(entry.Value, &s.CallTimeoutSeconds); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "sampleSeconds":
			if err := json.Unmarshal(entry.Value, &s.SampleSeconds); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "prompt":
			if err := json.Unmarshal(entry.Value, &s.Prompt); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "numPredict":
			if err := json.Unmarshal(entry.Value, &s.NumPredict); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "warmupNumPredict":
			if err := json.Unmarshal(entry.Value, &s.WarmupNumPredict); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		case "generationTimeoutSeconds":
			if err := json.Unmarshal(entry.Value, &s.GenerationTimeoutSeconds); err != nil {
				return s, fmt.Errorf("failed to parse value for key %q in settings file %s: %w", key, path, err)
			}
		}
	}

	return s, nil
}

// dimension holds the median and minimum values for a metric.
type dimension struct {
	Median float64
	Min    float64
}

// reference holds the reference measurements for a model.
type reference struct {
	NumCtx int
	CPU    dimension
	GPU    dimension
}

// Purpose: Load reference measurements for models from a JSON file.
// Details: Returns an empty map if the file does not exist.
// Inputs: path - the file system path to the references JSON file.
// Outputs: map[string]reference - a map of model tags to their reference data.
// Raises: error if the file exists but is not valid JSON.
func loadReferences(path string) (map[string]reference, error) {
	refs := make(map[string]reference)

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return refs, nil
		}
		return refs, fmt.Errorf("failed to read references file %s: %w", path, err)
	}

	var raw struct {
		Models map[string]struct {
			ReferenceDecode struct {
				NumCtx     int `json:"num_ctx"`
				CPUPercent struct {
					Median float64 `json:"median"`
					Min    float64 `json:"min"`
				} `json:"cpu_percent"`
				GPUPercent struct {
					Median float64 `json:"median"`
					Min    float64 `json:"min"`
				} `json:"gpu_percent"`
			} `json:"reference_decode"`
		} `json:"models"`
	}

	if err := json.Unmarshal(data, &raw); err != nil {
		return refs, fmt.Errorf("failed to parse references file %s: %w", path, err)
	}

	for tag, model := range raw.Models {
		refs[tag] = reference{
			NumCtx: model.ReferenceDecode.NumCtx,
			CPU: dimension{
				Median: model.ReferenceDecode.CPUPercent.Median,
				Min:    model.ReferenceDecode.CPUPercent.Min,
			},
			GPU: dimension{
				Median: model.ReferenceDecode.GPUPercent.Median,
				Min:    model.ReferenceDecode.GPUPercent.Min,
			},
		}
	}

	return refs, nil
}
