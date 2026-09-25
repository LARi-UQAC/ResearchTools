# Spec — mobile robot path planner and simulator

**Goal.** A 2-D simulator in which a mobile robot plans a collision-free path
across a grid with Theta*, then travels it under trapezoidal profiles applied to
its cylindrical coordinates, animated live in matplotlib.

**Contents.** The world, the coordinate convention, the settled design
decisions, the library constraints and the definition of done. Re-read on every
call, so it stays complete and does not grow. Not a task list — that is
`progress.md`.

## The world

| Item | Value |
|---|---|
| Grid | 64 x 64 cells |
| Cell | exactly the size of the robot |
| Obstacle | the centre 3 x 3 cells, static, drawn solid black |
| Robot | a triangle inscribed in one cell, pointing along its direction of travel |
| Start | cell (1,1), bottom-left, inside the map |
| Goal | the top-right cell |

## Coordinates — settled, do not re-derive

The robot's position is expressed in cylindrical coordinates `r(t)` and
`angle(t)`.

**The polar origin is the outer corner of cell (0,0)**, the bottom-left corner
of the grid. Consequences that hold everywhere in this project:

- `r` and `angle` are non-negative at every point of the map.
- `angle` sweeps roughly 0 to 90 degrees over the journey.
- There is **no quadrant crossing and no angle wrap**. Code must not contain
  unwrapping logic; if it seems necessary, the origin has been misplaced.

## Motion — settled, and the subtle part

Between two consecutive waypoints, `r(t)` and `angle(t)` **each** follow their
own trapezoidal velocity profile. The robot genuinely moves in polar
coordinates.

**Therefore the travelled path between two waypoints is an ARC, not the straight
line Theta* proved clear.** This is a real consequence and the most likely place
this project goes wrong: an arc can bulge into the obstacle even when the
straight segment between the same two waypoints was collision-free.

The design must **sample each arc and test every sample against the obstacle**.
A colliding arc is reported loudly — in the user interface and on stdout — and
is never silently accepted, smoothed, or clipped away.

**The final-time value is the TOTAL** for the whole path, start to goal. Each
segment receives a share proportional to its length, and its trapezoid is scaled
to fit that share. Velocity and acceleration are outputs, not inputs.

Robot **dynamics and kinematics are out of scope**: no mass, no inertia, no
wheel model, no steering limit.

## Display

Two axes in one matplotlib window.

**Map axes**: the grid; the obstacle as a solid black 3 x 3 block; the planned
path in green; the travelled trajectory in red, drawn progressively as the robot
moves; the robot triangle oriented along its motion; and below the robot a live
readout of the current `r(t)` and `angle(t)`.

**Velocity axes**: velocity against time, drawn progressively as the simulation
advances rather than shown complete from the start. Three curves:

- `dr/dt` and `d(angle)/dt`, the commanded velocities. Because each follows a
  trapezoidal profile, **each appears on screen as a trapezoid**, one per path
  segment. Showing that shape is the purpose of this plot.
- the resulting Cartesian speed, `sqrt(rdot^2 + (r * angledot)^2)`, which is
  **not** a trapezoid. The contrast between commanded profile and produced speed
  is the point.

Axes carry units and a legend.

**Resizing** the window rescales all content so it always fits: nothing is
clipped, the grid stays square, both axes stay readable.

## Controls

One row along the bottom of the window:

1. Button — compute the path with obstacle avoidance.
2. Button — start the simulation.
3. Button — stop.
4. Immediately right of Stop, a rectangle showing elapsed simulation time at
   0.1 second resolution.
5. A text input for the final time, defaulting to 5 seconds.

## Environment and constraints

- Python 3. Third-party libraries: **matplotlib and numpy only**. Buttons and
  the text box come from `matplotlib.widgets`. No tkinter, no PyQt, no other GUI
  toolkit, and no path-planning or robotics library — Theta* and the trapezoidal
  profiles are written for this project.
- **No hardcoded values.** Grid size, cell size, obstacle position and extent,
  start and goal cells, default final time, colours, sampling resolution, figure
  size and every tolerance live in `config.json`, read at run time. A pure
  mathematical constant of the domain is not configuration.
- Every source file has a matching test under `tests/`, written in the same step
  as the code. Code without its test is not done.
- Every test asserts at least one **failure path**, not only the happy path.
- Every function carries a header giving Purpose, Inputs, Outputs, and Raises
  where it raises.
- A new source file stays under 4000 tokens, roughly 300 to 400 lines, and so
  does its test. A module that would exceed that is two modules.

## Module map

Each file has one responsibility. Later plans import earlier modules by name.

| File | Responsibility |
|---|---|
| `config.json` | every configured value |
| `world.py` | grid, cell geometry, obstacle, grid / Cartesian / polar conversion |
| `planner.py` | Theta* with line-of-sight, returning waypoints |
| `trajectory.py` | trapezoidal profile, and time allocation across segments |
| `arcs.py` | arc sampling and collision verification |
| `render_map.py` | the map axes |
| `render_velocity.py` | the velocity axes |
| `app.py` | controls, clock, animation loop, wiring |

## Definition of done

The application launches; **Compute** produces a green path avoiding the
obstacle; **Start** animates the robot along it with the red trail growing and
the velocity curves growing beside it; the `r`/`angle` readout and the elapsed
clock update live; **Stop** halts it; changing the final time and recomputing
changes the duration; resizing keeps everything visible; and every module has a
passing test that includes a failure case.
