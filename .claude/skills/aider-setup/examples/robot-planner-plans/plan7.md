# Plan 7 — the application

**Goal.** The window, the four controls, the clock, and the animation loop that
advances simulated time and redraws both views.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

1. **Create `app.py`** importing `World`, `plan_path`, `build_trajectory`,
   `MapView` and `VelocityView`. It loads `config.json` — the only module that
   reads it from disk — and passes the parsed config to everything else.

2. **Build the figure** with the map axes above and the velocity axes below,
   leaving a strip along the bottom for the controls. Sizes come from the config.

3. **Add the controls in one row**, using `matplotlib.widgets`: a `Button`
   labelled Compute, a `Button` labelled Start, a `Button` labelled Stop, then
   **immediately right of Stop** a rectangle showing elapsed simulation time,
   and a `TextBox` for the final time defaulting to the config's value.

4. **Compute** reads the final time from the text box, runs `plan_path`, then
   `build_trajectory`, draws the green path, resets both views, and enables
   Start. If the text box does not parse as a positive number, it says so in the
   window and changes nothing — it does not fall back to the default silently.

5. **Report a colliding arc.** When `build_trajectory` returns colliding
   samples, state it in the window and print it to stdout, naming how many
   samples collided. Do not hide it, and do not refuse to draw — the point is
   that the operator sees the arc leave the planned line.

6. **Start** runs the animation over simulated time from 0 to the final time,
   stepping by the config's interval. Each step: advance the robot, append to
   the trail, append to the velocity curves, update the readout, and update the
   clock rectangle at **0.1 second resolution**. **Stop** halts it and leaves
   everything on screen; Start resumes from where it stopped.

7. **Keep simulated time separate from wall-clock time.** The clock shows
   simulated time so a slow machine and a fast one produce the same trajectory.

8. **Add `main()`** and the `if __name__ == "__main__"` guard.

9. **Write `tests/test_app.py`** under the `Agg` backend, driving the callbacks
   directly rather than clicking. Cover: Compute with the default time producing
   a path and a trajectory; Start advancing simulated time and growing both the
   trail and the velocity curves; Stop leaving the sample count unchanged and
   Start resuming from it; the clock string formatted to one decimal; a
   colliding trajectory setting the visible message; and the failure paths — a
   non-numeric final time leaving the previous value in force with a message
   shown, and Start before Compute doing nothing rather than raising.

10. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_app.py` passes and the whole suite is green.
