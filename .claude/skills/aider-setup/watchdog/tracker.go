package main

// reading holds the data from a single poll of the model server.
type reading struct {
	Model         string
	CPUPercent    float64
	GPUPercent    *float64
	ContextLength int
	State         string
	Plan          string
}

// tracker keeps the count of consecutive low readings to detect stalls.
type tracker struct {
	refs  map[string]reference
	s     settings
	count int
}

// Purpose: Create a new tracker with the given references and settings.
// Inputs: refs - map of model references, s - settings.
// Outputs: *tracker - the initialized tracker.
func newTracker(refs map[string]reference, s settings) *tracker {
	return &tracker{
		refs:  refs,
		s:     s,
		count: 0,
	}
}

// Purpose: Update the tracker with a new reading and return true if a stall is detected.
// Inputs: r - the new reading.
// Outputs: bool - true if a stall is detected (count reached lowReadings and then reset).
func (t *tracker) update(r reading) bool {
	// Check if judgment is allowed
	if r.Model == "" {
		return false
	}
	if !contains(t.s.WatchedStates, r.State) {
		return false
	}
	ref, ok := t.refs[r.Model]
	if !ok {
		return false
	}
	if r.ContextLength != ref.NumCtx {
		return false
	}

	// Check if reading is low
	isLow := true
	if ref.CPU.Median >= t.s.NegligibleReferencePercent {
		if r.CPUPercent >= ref.CPU.Min {
			isLow = false
		}
	}
	if ref.GPU.Median >= t.s.NegligibleReferencePercent {
		if r.GPUPercent == nil {
			// "a nil GPU reading on a judged GPU dimension means the reading is not judged"
			// This implies we should not count it as low, nor reset?
			// "A reading that is not low resets the count."
			// If it's not judged, is it "not low"? Usually "not judged" means ignore for the low check,
			// but if we can't determine if it's low, we probably shouldn't count it as low.
			// Let's assume it breaks the streak (resets) or just doesn't count as low.
			// Spec: "A reading is low when every dimension... is under... A reading that is not low resets the count."
			// If GPU is nil, we can't say it's under min. So it's not low.
			isLow = false
		} else if *r.GPUPercent >= ref.GPU.Min {
			isLow = false
		}
	}

	if isLow {
		t.count++
		if t.count >= t.s.LowReadings {
			t.count = 0
			return true
		}
	} else {
		t.count = 0
	}

	return false
}

// Purpose: Check if a slice contains a string.
// Inputs: slice - the slice to check, val - the value to look for.
// Outputs: bool - true if the value is found.
func contains(slice []string, val string) bool {
	for _, item := range slice {
		if item == val {
			return true
		}
	}
	return false
}
