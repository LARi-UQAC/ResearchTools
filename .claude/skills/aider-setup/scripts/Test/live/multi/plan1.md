# Plan 1 - grid path

**Goal.** `scripts/grid_path.py` tells whether two cells see each other and measures a path.

**Contents.** Numbered steps, each naming its file. Done means the tests pass and assert a failure path.

1. **Create `scripts/grid_path.py`.** Standard library only, pure functions, no printing, no test code.

2. **Add `line_of_sight(grid, a, b) -> bool`** telling whether every cell on the straight segment from cell a to cell
   b is free. Walk the cells of the segment with the integer line algorithm of Bresenham. A segment that starts or
   ends on an obstacle has no line of sight. A cell outside the grid raises `ValueError` naming the cell.

3. **Add `path_length(waypoints) -> float`** returning the sum of the straight distances between consecutive cells.
   One waypoint gives 0.0. An empty list raises `ValueError`.

4. **Write `scripts/Test/test_grid_path.py`**, following the test conventions of the spec. Cover: line of sight across an empty
   grid; line of sight blocked by a wall; a diagonal segment; an endpoint on an obstacle; the length of a path that
   follows a 3-4-5 triangle; the length of a single waypoint; and the failure paths, a cell outside the grid and an
   empty waypoint list, each raising `ValueError`.

**Done when** `scripts/Test/test_grid_path.py` passes.
