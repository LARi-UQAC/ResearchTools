package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"time"
)

type stat struct {
	Median float64
	Min    float64
}

type referenceRecord struct {
	MeasuredAt string
	NumCtx     int
	DecodeTPS  float64
	CPU        stat
	GPU        *stat
	Samples    int
	Source     string
}

type refDeps struct {
	runner runner
	getter getter
	post   func(url string, body []byte, timeout time.Duration) ([]byte, error)
	now    func() time.Time
	sleep  func(time.Duration)
}

// Purpose: Calculate median and minimum of a series of values.
// Inputs: values - slice of float64 values.
// Outputs: stat - struct with Median and Min.
// Raises: error if values is empty.
func summarize(values []float64) (stat, error) {
	if len(values) == 0 {
		return stat{}, fmt.Errorf("empty series")
	}
	sorted := make([]float64, len(values))
	copy(sorted, values)
	sort.Float64s(sorted)

	minVal := sorted[0]
	median := medianOf(sorted)

	return stat{Median: median, Min: minVal}, nil
}

func medianOf(sorted []float64) float64 {
	n := len(sorted)
	if n%2 == 0 {
		return (sorted[n/2-1] + sorted[n/2]) / 2
	}
	return sorted[n/2]
}

// Purpose: Measure reference CPU and GPU load for a model.
// Inputs: d - dependencies, tag - model tag, s - settings.
// Outputs: referenceRecord - the measured reference data.
// Raises: error if measurement fails.
func measureReference(d refDeps, tag string, s settings) (referenceRecord, error) {
	timeout := time.Duration(s.CallTimeoutSeconds) * time.Second

	// 1. Warmup
	warmupBody := map[string]interface{}{
		"model":   tag,
		"prompt":  s.Prompt,
		"stream":  false,
		"options": map[string]interface{}{"num_predict": s.WarmupNumPredict},
	}
	warmupJSON, _ := json.Marshal(warmupBody)
	// Loading a large model into memory takes far longer than a status call, so the warm-up gets the
	// generation timeout.
	if _, err := d.post(s.OllamaURL+"/api/generate", warmupJSON, time.Duration(s.GenerationTimeoutSeconds)*time.Second); err != nil {
		return referenceRecord{}, fmt.Errorf("warmup failed: %w", err)
	}

	// 2. Read context length
	model, contextLength, err := readOllamaPS(d.getter, s.OllamaURL, timeout)
	if err != nil {
		return referenceRecord{}, fmt.Errorf("failed to read ollama ps: %w", err)
	}
	if model != tag {
		return referenceRecord{}, fmt.Errorf("model %s not loaded, found %s", tag, model)
	}

	// 3. Measurement loop
	var cpuSamples []float64
	var gpuSamples []float64
	var evalCount int
	var evalDuration float64

	var lastCPUSeconds float64
	var lastTime time.Time
	firstPoll := true

	generationBody := map[string]interface{}{
		"model":   tag,
		"prompt":  s.Prompt,
		"stream":  false,
		"options": map[string]interface{}{"num_predict": s.NumPredict},
	}
	generationJSON, _ := json.Marshal(generationBody)

	// Start generation in a goroutine to allow sampling
	generationDone := make(chan bool)
	var generationErr error
	go func() {
		resp, err := d.post(s.OllamaURL+"/api/generate", generationJSON, time.Duration(s.GenerationTimeoutSeconds)*time.Second)
		if err != nil {
			generationErr = err
			generationDone <- false
			return
		}
		var result struct {
			EvalCount    int     `json:"eval_count"`
			EvalDuration float64 `json:"eval_duration"` // nanoseconds, as Ollama reports it
		}
		if err := json.Unmarshal(resp, &result); err != nil {
			generationErr = err
			generationDone <- false
			return
		}
		evalCount = result.EvalCount
		evalDuration = result.EvalDuration
		generationDone <- true
	}()

	// One sample: the model server's CPU seconds since the previous sample, and the GPU load.
	// A sample with keep false only sets the CPU baseline: taken before the model decodes, its GPU
	// and CPU would be idle values and drag the measured minimum to zero.
	sample := func(keep bool) {
		now := d.now()
		rows, err := readProcessTable(d.runner, timeout)
		if err != nil {
			return // this sample is skipped, the next one tries again
		}
		cpuSeconds := serverCPUSeconds(rows, s.ModelServerNames)
		if keep && !firstPoll {
			elapsed := now.Sub(lastTime).Seconds()
			if elapsed > 0 {
				cpuSamples = append(cpuSamples, (cpuSeconds-lastCPUSeconds)/elapsed*100)
			}
		}
		firstPoll = false
		lastCPUSeconds = cpuSeconds
		lastTime = now
		if !keep {
			return
		}
		if gpuPercent, err := readGPUPercent(d.runner, timeout); err == nil {
			gpuSamples = append(gpuSamples, gpuPercent)
		}
	}

	ticker := time.NewTicker(time.Duration(s.SampleSeconds) * time.Second)
	defer ticker.Stop()

	// The first sample is the baseline the next ones are compared with. A last one is taken only when
	// the generation ended before any tick, so even a very short generation yields a reading; otherwise
	// the tail of the generation, partly idle, would lower the measured minimum.
	sample(false)
sampling:
	for {
		select {
		case <-generationDone:
			if len(cpuSamples) == 0 {
				sample(true)
			}
			break sampling
		case <-ticker.C:
			sample(true)
		}
	}

	// Check generation error
	if generationErr != nil {
		return referenceRecord{}, fmt.Errorf("generation failed: %w", generationErr)
	}

	if len(cpuSamples) == 0 {
		return referenceRecord{}, fmt.Errorf("no CPU samples collected")
	}

	cpuStat, err := summarize(cpuSamples)
	if err != nil {
		return referenceRecord{}, err
	}

	var gpuStat *stat
	if len(gpuSamples) > 0 {
		g, err := summarize(gpuSamples)
		if err != nil {
			return referenceRecord{}, err
		}
		gpuStat = &g
	}

	decodeTPS := 0.0
	if evalDuration > 0 {
		decodeTPS = float64(evalCount) / (evalDuration / 1e9)
	}

	return referenceRecord{
		MeasuredAt: d.now().Format(time.RFC3339),
		NumCtx:     contextLength,
		DecodeTPS:  decodeTPS,
		CPU:        cpuStat,
		GPU:        gpuStat,
		Samples:    len(cpuSamples),
		Source:     "aider-watchdog reference",
	}, nil
}

// Purpose: Write the reference record to the JSON file.
// Inputs: path - file path, tag - model tag, rec - reference record.
// Outputs: error.
// Raises: error if file operations fail.
func writeReference(path, tag string, rec referenceRecord) error {
	var data map[string]interface{}

	if fileExists(path) {
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if err := json.Unmarshal(content, &data); err != nil {
			return fmt.Errorf("existing file is not valid JSON: %w", err)
		}
	} else {
		data = make(map[string]interface{})
	}

	models, ok := data["models"].(map[string]interface{})
	if !ok {
		models = make(map[string]interface{})
	}

	model, ok := models[tag].(map[string]interface{})
	if !ok {
		model = make(map[string]interface{})
	}

	refDecode := map[string]interface{}{
		"num_ctx": rec.NumCtx,
		"cpu_percent": map[string]interface{}{
			"median": rec.CPU.Median,
			"min":    rec.CPU.Min,
		},
		"samples":     rec.Samples,
		"source":      rec.Source,
		"measured_at": rec.MeasuredAt,
		"decode_tps":  rec.DecodeTPS,
	}

	if rec.GPU != nil {
		refDecode["gpu_percent"] = map[string]interface{}{
			"median": rec.GPU.Median,
			"min":    rec.GPU.Min,
		}
	}

	model["reference_decode"] = refDecode
	models[tag] = model
	data["models"] = models

	tmpPath := path + ".tmp"
	content, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(tmpPath, content, 0644); err != nil {
		return err
	}
	return os.Rename(tmpPath, path)
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return !os.IsNotExist(err)
}
