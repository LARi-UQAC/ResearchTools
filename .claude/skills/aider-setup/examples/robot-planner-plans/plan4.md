# Plan 4 — arc sampling and collision verification

**Goal.** Drive `r` and `angle` by their own trapezoids between two waypoints,
sample the curve that actually results, and prove it clears the obstacle.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

**Why this plan exists.** Theta* guarantees the straight line between two
waypoints is clear. This project does not travel that straight line: driving `r`
and `angle` independently traces an **arc**, which can bulge into the obstacle
even when the straight segment was clear. Nothing else in the project checks
that.

1. **Create `arcs.py`** importing `World` and `TrapezoidProfile`. It imports no
   matplotlib.

2. **Add `segment_arc(world, cell_a, cell_b, duration, samples)`.** Convert both
   cell centres to polar with `world.xy_to_polar`. Build one `TrapezoidProfile`
   for `r` and one for `angle`. At each of `samples` times evenly spaced over
   `duration`, evaluate both and convert back with `world.polar_to_xy`. Return a
   list of records carrying `t`, `x`, `y`, `r`, `angle`, `r_dot`, `angle_dot`.

3. **Add `cartesian_speed(record)`** returning `sqrt(r_dot^2 + (r *
   angle_dot)^2)`. Plan 6 plots it beside the two commanded velocities.

4. **Add `verify_arc(world, arc)`** returning the list of samples whose `(x, y)`
   falls in an obstacle cell. Empty means clear.

5. **Add `build_trajectory(world, waypoints, total_time)`** calling
   `allocate_times`, then `segment_arc` per segment, concatenating into one
   time-ordered list with `t` accumulating across segments rather than
   restarting at each one.

6. **Report a collision loudly and never hide it.** `build_trajectory` returns
   both the samples and a list of colliding ones. It does **not** smooth,
   clip, or silently drop a colliding arc, and it does not raise — the
   application has to draw the result and say so.

7. **Write `tests/test_arcs.py`.** Cover: an arc's first and last samples
   landing on the two cell centres within tolerance; `t` increasing across a
   concatenated multi-segment trajectory; `cartesian_speed` zero at both ends of
   a segment because both profiles start and end at rest; **an arc that bulges
   into the obstacle being reported** — construct two waypoints on opposite
   sides of the centre block whose straight line clears it, and assert
   `verify_arc` returns a non-empty list, which is this plan's whole point; a
   clear arc returning an empty list; and the failure path of `segment_arc`
   with zero samples raising `ValueError`.

8. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_arcs.py` passes, including the bulging-arc case.
