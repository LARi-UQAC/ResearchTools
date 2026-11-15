# Plan 2 - trapezoid speed

**Goal.** `scripts/trapezoid.py` gives the phase durations and the speed along one straight segment with a trapezoid
speed profile.

**Contents.** Numbered steps, each naming its file. Done means the tests pass and assert a failure path.

1. **Create `scripts/trapezoid.py`.** Standard library only, pure functions, no printing, no test code. It does not
   import any other module of the project.

2. **Add `profile(distance, v_max, accel) -> dict`** returning the phase durations `t_accel`, `t_cruise`, `t_decel`,
   the total time and the peak speed, from the closed-form formulas of constant acceleration. When `distance` is too
   short to reach `v_max` the profile is a triangle: `t_cruise` is zero and the peak speed is below `v_max`. A
   distance of zero gives a total time of zero. A negative distance, or a `v_max` or `accel` that is not positive,
   raises `ValueError` naming the value.

3. **Add `speed_at(distance, v_max, accel, t) -> float`.** The speed starts and ends at zero. A time before zero or
   after the total time is clamped to the nearest end.

4. **Write `scripts/Test/test_trapezoid.py`**, following the test conventions of the spec. Cover: a long segment with a cruise
   phase and its total time; a short segment giving a triangle with no cruise; the speed equal to zero at both ends;
   the speed never above `v_max`; the clamping outside the time range; and the failure paths, a negative distance and
   a zero acceleration, each raising `ValueError`.

**Done when** `scripts/Test/test_trapezoid.py` passes.
