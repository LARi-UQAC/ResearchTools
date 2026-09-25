# Plan 6 — the velocity view

**Goal.** A second axes plotting the two commanded velocities and the resulting
Cartesian speed against time, growing as the simulation advances.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

**Why this is its own plan.** The map view and this view together exceed the
4000-token ceiling for one file, so they are two modules. They share nothing but
the trajectory samples.

1. **Create `render_velocity.py`.** It imports `cartesian_speed` from `arcs.py`
   and nothing from `render_map.py`: the two views are independent.

2. **Add `VelocityView(ax, config)`** creating three empty lines with a legend
   and axis labels — time in seconds on x, velocity on y — reading colours and
   labels from the config.

3. **The three curves are** `dr/dt`, `d(angle)/dt`, and the Cartesian speed
   `sqrt(r_dot^2 + (r * angle_dot)^2)`. The first two follow trapezoidal
   profiles and so **appear as trapezoids**, one per path segment; the third
   does not, and the contrast is the reason this plot exists.

4. **Add `VelocityView.append(sample)`** extending all three lines by one point
   from one trajectory record, and `VelocityView.reset()` clearing them. The
   curves grow with the simulation; they are never drawn complete in advance.

5. **Add `VelocityView.autoscale()`** widening the limits to the data seen so
   far, called after appending. The x limit follows elapsed time, the y limit
   the largest magnitude of the three curves, with the margin from the config.

6. **Units differ between the curves** — `dr/dt` in cells per second,
   `d(angle)/dt` in radians per second — so say so in the legend rather than
   implying one scale means one unit. Note it in the y label too.

7. **Write `tests/test_render_velocity.py`** under the `Agg` backend. Cover:
   three lines created with a legend; `append` extending each by exactly one
   point; `reset` emptying all three; **the trapezoid property** — feed one
   segment's samples and assert `dr/dt` rises, holds a constant value, then
   falls, which is what makes the plot worth having; `autoscale` covering the
   data range; and the failure path of `append` with a record missing a key
   raising `KeyError` naming it rather than plotting a gap.

8. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_render_velocity.py` passes, including the trapezoid
shape check.
