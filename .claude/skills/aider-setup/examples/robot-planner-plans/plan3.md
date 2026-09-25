# Plan 3 — trapezoidal profiles and time allocation

**Goal.** A trapezoidal velocity profile that moves one scalar from a start
value to an end value in a given duration, and the rule that divides the total
final time among the path's segments.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

1. **Create `trajectory.py`.** Pure functions and small classes only: it imports
   no matplotlib and touches no file.

2. **Add `TrapezoidProfile(start, end, duration, accel_fraction)`** where
   `accel_fraction` comes from `config.json` and is the share of the duration
   spent accelerating, equal to the share spent decelerating. Expose
   `value(t)` and `velocity(t)`.

3. **Make the profile exact at its ends.** `value(0) == start`,
   `value(duration) == end`, and `velocity(0) == velocity(duration) == 0`. The
   cruise velocity follows from those constraints; it is derived, never
   configured. Clamp `t` outside `[0, duration]` to the nearest end rather than
   extrapolating.

4. **Handle the degenerate cases explicitly**: `start == end` gives a profile
   that is zero everywhere and does not divide by zero; `accel_fraction` of 0.5
   gives a triangular profile with no cruise phase, which is legal; a
   `duration` of zero or negative raises `ValueError` naming the value.

5. **Add `allocate_times(waypoints, total_time, world)`** returning one duration
   per segment, proportional to the segment's straight-line length in continuous
   coordinates, summing **exactly** to `total_time`. Assign the rounding
   remainder to the last segment so the sum is exact rather than nearly right.

6. **Write `tests/test_trajectory.py`.** Cover: the endpoint and zero-velocity
   conditions; the integral of `velocity` over the duration equalling
   `end - start` within tolerance, which is the property that makes the profile
   correct; the triangular case; the equal-value case; allocation summing to
   `total_time` exactly and dividing a two-segment path in proportion to length;
   and the failure paths — a zero duration raising `ValueError`, and
   `allocate_times` with fewer than two waypoints raising rather than returning
   an empty list.

7. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_trajectory.py` passes, including the integral check.
