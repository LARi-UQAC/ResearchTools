# Plan 1 — the world model

**Goal.** The grid, the obstacle and every coordinate conversion the rest of the
project depends on, plus the configuration file that holds every number.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

1. **Create `config.json`.** Every value the project uses, none of them written
   in code. At minimum: `grid.cols` 64, `grid.rows` 64, `grid.cell_size` 1.0,
   `obstacle.center_cols` 3, `obstacle.center_rows` 3, `start.cell` [1,1],
   `goal.cell` [62,62], `time.default_final_s` 5.0, `time.clock_resolution_s`
   0.1, `arc.samples_per_segment` 64, `colors.path` "green",
   `colors.trail` "red", `colors.obstacle` "black", `figure.width_in`,
   `figure.height_in`.

2. **Create `world.py` with a `World` class** built from the parsed config. It
   exposes `cols`, `rows`, `cell_size`, and the obstacle's cell extent computed
   from the grid centre — not written as literal cell indices, because the
   obstacle is defined as "the centre 3 x 3".

3. **Add `World.is_obstacle(col, row)`** returning True for a cell inside the
   obstacle block. Out-of-range cells raise `IndexError` with a message naming
   the offending cell and the grid size.

4. **Add `World.cell_to_xy(col, row)`** returning the continuous coordinates of
   that cell's **centre**, and `World.xy_to_cell(x, y)` returning the cell
   containing a continuous point. These two are inverse for cell centres, and
   the test must assert that round trip.

5. **Add `World.xy_to_polar(x, y)`** returning `(r, angle_rad)` measured from
   the **outer corner of cell (0,0)**, which is continuous coordinate (0,0), and
   `World.polar_to_xy(r, angle_rad)` as its inverse. Because the origin is that
   corner, `r >= 0` and `0 <= angle <= pi/2` for every point of the map, so
   **write no angle-unwrapping logic**.

6. **Write `tests/test_world.py`.** Cover: obstacle occupancy true at the centre
   and false at the corners; the cell/xy round trip; the xy/polar round trip;
   the start cell (1,1) giving a small positive `r` and an angle near 45
   degrees; and the failure paths — an out-of-range cell raising `IndexError`,
   and a config missing a required key raising with the key named rather than
   defaulting.

7. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_world.py` passes and `config.json` holds every number
this plan introduced.
