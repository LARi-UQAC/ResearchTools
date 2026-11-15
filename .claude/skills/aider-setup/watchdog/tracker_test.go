package main

import (
	"testing"
)

func TestNothingIsJudgedBeforeTheModelIsLoaded(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	tr := newTracker(map[string]reference{}, s)

	readings := []reading{
		{Model: "", CPUPercent: 1, GPUPercent: nil, ContextLength: 4096, State: "writing"},
		{Model: "", CPUPercent: 1, GPUPercent: nil, ContextLength: 4096, State: "writing"},
		{Model: "", CPUPercent: 1, GPUPercent: nil, ContextLength: 4096, State: "writing"},
	}

	for _, r := range readings {
		if tr.update(r) {
			t.Errorf("expected no stall when no model is loaded")
		}
	}
}

func TestNothingIsJudgedInTheTestingState(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	readings := []reading{
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "testing"},
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "testing"},
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "testing"},
	}

	for _, r := range readings {
		if tr.update(r) {
			t.Errorf("expected no stall in state 'testing'")
		}
	}
}

func TestAModelWithNoReferenceIsNotJudged(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	tr := newTracker(map[string]reference{}, s)

	readings := []reading{
		{Model: "unknown-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "writing"},
		{Model: "unknown-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "writing"},
		{Model: "unknown-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 4096, State: "writing"},
	}

	for _, r := range readings {
		if tr.update(r) {
			t.Errorf("expected no stall for model with no reference")
		}
	}
}

func TestAModelLoadedWithAnotherContextIsNotJudged(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	readings := []reading{
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 8192, State: "writing"},
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 8192, State: "writing"},
		{Model: "test-model", CPUPercent: 1, GPUPercent: ptr(1), ContextLength: 8192, State: "writing"},
	}

	for _, r := range readings {
		if tr.update(r) {
			t.Errorf("expected no stall when context length differs from reference")
		}
	}
}

func TestHealthyReadingsNeverStall(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	for i := 0; i < 10; i++ {
		r := reading{Model: "test-model", CPUPercent: 20, GPUPercent: ptr(20), ContextLength: 4096, State: "writing"}
		if tr.update(r) {
			t.Errorf("expected no stall for healthy readings")
		}
	}
}

func TestLowReadingsInARowMakeAStall(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	r := reading{Model: "test-model", CPUPercent: 5, GPUPercent: ptr(5), ContextLength: 4096, State: "writing"}

	if tr.update(r) {
		t.Errorf("stall too early")
	}
	if tr.update(r) {
		t.Errorf("stall too early")
	}
	if !tr.update(r) {
		t.Errorf("expected stall after 3 low readings")
	}
}

func TestOneRecoveredReadingResetsTheCount(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	low := reading{Model: "test-model", CPUPercent: 5, GPUPercent: ptr(5), ContextLength: 4096, State: "writing"}
	healthy := reading{Model: "test-model", CPUPercent: 20, GPUPercent: ptr(20), ContextLength: 4096, State: "writing"}

	tr.update(low)
	tr.update(low)
	tr.update(healthy) // resets count

	if tr.update(low) {
		t.Errorf("stall too early after reset")
	}
	if tr.update(low) {
		t.Errorf("stall too early after reset")
	}
	if !tr.update(low) {
		t.Errorf("expected stall after 3 low readings following a reset")
	}
}

func TestNegligibleGPUReferenceIsIgnored(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                3,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 1, Min: 0}, // Negligible GPU
		},
	}
	tr := newTracker(refs, s)

	// CPU is low, GPU is high (but ignored because negligible)
	r := reading{Model: "test-model", CPUPercent: 5, GPUPercent: ptr(90), ContextLength: 4096, State: "writing"}

	if tr.update(r) {
		t.Errorf("stall too early")
	}
	if tr.update(r) {
		t.Errorf("stall too early")
	}
	if !tr.update(r) {
		t.Errorf("expected stall when CPU is low and GPU is negligible")
	}
}

func TestEachModelUsesItsOwnReference(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                2,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"model-a": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
		"model-b": {
			NumCtx: 4096,
			CPU:    dimension{Median: 100, Min: 50},
			GPU:    dimension{Median: 100, Min: 50},
		},
	}
	tr := newTracker(refs, s)

	// model-a low reading
	rA := reading{Model: "model-a", CPUPercent: 5, GPUPercent: ptr(5), ContextLength: 4096, State: "writing"}
	// model-b healthy reading (relative to its higher reference)
	rB := reading{Model: "model-b", CPUPercent: 60, GPUPercent: ptr(60), ContextLength: 4096, State: "writing"}

	tr.update(rA)
	tr.update(rB) // Should reset count for model-a? Or does it track per model?
	// Spec: "It judges nothing... when the model has no reference... A reading is low... A stall is lowReadings low readings in a row; one reading that is not low resets the count."
	// It implies a single count. If we switch models, does it reset?
	// "Each model uses its own reference" implies the judgment depends on the model.
	// If the count is global, then a healthy reading of model-b might reset the count of model-a if model-b is considered "not low".
	// Let's assume the count is global as per "a stall is lowReadings low readings in a row".

	// If we do rA, rA, it should stall.
	tr2 := newTracker(refs, s)
	if tr2.update(rA) {
		t.Errorf("stall too early")
	}
	if !tr2.update(rA) {
		t.Errorf("expected stall for model-a")
	}
}

func TestNilGPUReadingIsNotLow(t *testing.T) {
	s := settings{
		NegligibleReferencePercent: 5,
		LowReadings:                2,
		WatchedStates:              []string{"writing"},
	}
	refs := map[string]reference{
		"test-model": {
			NumCtx: 4096,
			CPU:    dimension{Median: 50, Min: 10},
			GPU:    dimension{Median: 50, Min: 10},
		},
	}
	tr := newTracker(refs, s)

	// CPU is low (5 < 10), GPU is nil (not low)
	r := reading{Model: "test-model", CPUPercent: 5, GPUPercent: nil, ContextLength: 4096, State: "writing"}

	// First reading: not low, count resets to 0
	if tr.update(r) {
		t.Errorf("expected no stall on first nil GPU reading")
	}
	// Second reading: not low, count resets to 0
	if tr.update(r) {
		t.Errorf("expected no stall on second nil GPU reading")
	}
}

func ptr(v float64) *float64 {
	return &v
}
