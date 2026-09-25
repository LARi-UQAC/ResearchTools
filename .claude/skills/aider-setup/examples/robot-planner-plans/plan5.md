# Plan 5 — the map view

**Goal.** The matplotlib axes showing the grid, the obstacle, the planned path,
the growing trail, the robot, and the live polar readout, rescaling on resize.

**Contents.** Numbered steps, each naming its file. Done means the test passes
and asserts a failure path.

**Testing note.** Use the `Agg` backend in the test so nothing opens a window.
Assert on the artists the module creates — their number, colours and data —
never on pixels.

1. **Create `render_map.py`** importing `World`. It reads colours, sizes and the
   figure geometry from the config passed in, never from literals.

2. **Add `MapView(ax, world, config)`** drawing the static scene once: grid
   lines at every cell boundary, the obstacle as a filled black rectangle
   covering exactly the centre 3 x 3 cells, and equal aspect so cells are square.

3. **Add `MapView.draw_path(cells)`** drawing the planned path as a green
   polyline through the cell centres. Calling it again replaces the previous
   path rather than accumulating artists.

4. **Add `MapView.set_robot(x, y, heading_rad)`** placing a triangle inscribed
   in one cell, pointing along `heading`. The triangle is built from the cell
   size, so it stays one cell across at any zoom.

5. **Add `MapView.append_trail(x, y)`** extending the red travelled trajectory
   by one point, and `MapView.reset_trail()` clearing it.

6. **Add `MapView.set_readout(r, angle_rad)`** writing the current values as
   text positioned **below the robot**, moving with it, angle shown in degrees.

7. **Handle resize.** Connect to the figure's `resize_event` and keep the map
   fitted with the grid square and nothing clipped. The triangle and the text
   keep their size in data coordinates, so they scale with the content.

8. **Write `tests/test_render_map.py`.** Cover: the obstacle patch covering
   exactly the configured centre cells; `draw_path` producing one green line
   whose vertex count matches the waypoints, and replacing rather than
   accumulating on a second call; the trail growing by one point per
   `append_trail` and emptying on reset; the triangle having three vertices and
   rotating with `heading`; the readout text containing both values; and the
   failure path of `draw_path` with fewer than two cells raising `ValueError`.

9. **Update `requirements.txt`.** Add every third-party package the
   modules in this plan actually import, one per line, creating the file if
   it is absent and leaving any line already there untouched. Add nothing
   this plan does not import. **Do not install anything** - the run cannot,
   and a person installs it in the morning after reading the file.

**Done when** `tests/test_render_map.py` passes under the `Agg` backend.
