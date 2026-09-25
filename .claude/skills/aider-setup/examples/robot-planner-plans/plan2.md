# Plan 2 — Theta* path planning

**Goal.** Waypoints from the start cell to the goal cell that avoid the
obstacle, using Theta* so the path is made of straight lines between visible
cells rather than following grid edges.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

1. **Create `planner.py`** importing `World` from `world.py`. It reads nothing
   from disk itself: the caller passes the world.

2. **Add `line_of_sight(world, a, b)`**, True when the straight segment between
   the centres of cells `a` and `b` crosses no obstacle cell. Walk the segment
   with a supersampled Bresenham or an equivalent, using the sampling density
   from `config.json`. This function is what separates Theta* from A*, so it
   gets its own tests.

3. **Add `plan_path(world, start, goal)`** implementing Theta*. Keep the A*
   skeleton — open set, g scores, came-from — with the Theta* change: when
   relaxing a neighbour, if the neighbour has line of sight to the parent's
   parent, attach it to the grandparent instead, shortening the path.

4. **Return a list of cells** from start to goal inclusive, the start first.
   Raise a `ValueError` naming both cells when no path exists — never return an
   empty list, which a caller reads as "arrived".

5. **Refuse a start or goal inside the obstacle** with a `ValueError` naming
   which one and its cell. This is a real case: a student editing `config.json`
   will hit it.

6. **Write `tests/test_planner.py`.** Cover: a clear corridor giving a
   two-waypoint path, start and goal only, because line of sight spans it; a
   path around the centre obstacle whose every waypoint is outside the obstacle;
   `line_of_sight` False through the obstacle and True beside it; **the Theta*
   property** that on an open grid the returned path has fewer waypoints than
   the number of cells an A* path would visit; and the failure paths — no path
   available raising `ValueError`, and a start inside the obstacle raising with
   the cell named.

7. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_planner.py` passes and `plan_path` returns waypoints
avoiding the centre block.
