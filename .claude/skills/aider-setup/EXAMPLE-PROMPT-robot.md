# Example planning prompt — mobile robot path planner

**Goal.** A worked example of the prompt a student gives to a *cloud* model to
produce the `spec.md`, `progress.md` and `plan<N>.md` files that the nightly
local pipeline then executes.

**Contents.** The prompt itself, ready to copy, plus a short note on why it is
shaped the way it is. It is an example of *planning*, not of coding: nothing
here is executed, and the local model never sees this file — it sees only the
three documents this prompt produces.

---

## Why the prompt looks like this

Three things drive its shape, and they are the parts worth studying:

1. **The output files have token ceilings**, so the prompt states them as hard
   limits. A plan that does not fit is not a long plan, it is two plans.
2. **The executing model's context is dropped between plans.** Anything plan 4
   needs to know must be in `spec.md`, in `progress.md`, or in code already on
   disk — never "as we established in plan 3".
3. **Three design questions were resolved before planning began.** Each had a
   defensible wrong answer that would only have surfaced hours into a run. They
   are stated as settled decisions so the planning model cannot quietly pick
   differently.

---

## The prompt

```text
You are writing the planning documents for a project that a small local coding
model will build overnight, one plan at a time, with no human present. You write
NO code. You produce exactly these files, and nothing else:

    docs/superpowers/plans/spec.md
    docs/superpowers/plans/progress.md
    docs/superpowers/plans/plan1.md  ...  plan7.md

=== HARD LIMITS ===

**Before writing anything, read `~\.config\aider\context-budget.json`.**
It holds the only copy of these numbers, and `aider-plan.ps1` reads that same
file to enforce them, so a figure taken from anywhere else can disagree with
what the night will actually accept. Do not copy the numbers into your answer
as a table; use them.

Which key governs which output:

    spec.md                     ceilings["spec.md"]
    progress.md                 ceilings["progress.md"]
    each plan<N>.md             ceilings["plan.md"]
    any NEW source file         ceilings["code_file_output"]
    any NEW test file           ceilings["test_file_output"]
    files touched by one plan   plan.max_files_touched   (aim for 2)

These are budgets the harness enforces, not style preferences. If you cannot
read that file, say so and stop rather than assuming a figure: a plan set built
against a guessed ceiling is rejected at 2 a.m. for a reason nothing in it
explains.

Two consequences you must design around:

  - The executing model's CONTEXT IS DROPPED between plans. A plan may rely only
    on spec.md, on progress.md, and on code already written to disk. Never write
    "as decided in plan 2" or "the helper we added earlier" without naming the
    file and function.
  - A step that would produce more than `ceilings["code_file_output"]` tokens of
    new code is two steps in two plans. Say so rather than writing a large step.
  - NOTHING IS INSTALLED DURING THE RUN. Every plan that introduces a
    third-party import must carry a step naming `requirements.txt` and the
    package it adds, one package per line. The person installs it in the
    morning. A plan that imports a package without declaring it produces a
    test failure whose cause is invisible until someone reads the imports of
    seven modules.

=== WHAT IS BEING BUILT ===

A 2-D mobile robot simulator with path planning and animated playback.

World
  - A 64 x 64 grid. One cell is exactly the size of the robot.
  - A static obstacle occupies the centre 3 x 3 cells.
  - The robot is drawn as a triangle inscribed in one cell, pointing along its
    direction of travel.
  - Start: cell (1,1), the bottom-left inside the map. Goal: the top-right cell.

Position
  - The robot's position is expressed in cylindrical coordinates r(t) and
    angle(t).
  - THE POLAR ORIGIN IS THE OUTER CORNER OF CELL (0,0), the bottom-left corner
    of the grid. r and angle are therefore non-negative everywhere, and angle
    sweeps roughly 0 to 90 degrees over the journey. There is no quadrant
    crossing and no angle wrap anywhere in this project.

Path planning
  - Theta* on the grid, avoiding the obstacle. Theta* returns straight-line
    waypoints, unlike A*, and that difference matters below.

Motion
  - Between two consecutive waypoints, r(t) and angle(t) EACH follow their own
    trapezoidal velocity profile. The robot genuinely moves in polar
    coordinates.
  - BECAUSE OF THAT, the path actually travelled between two waypoints is an ARC
    and not the straight line Theta* proved collision-free. This is a real
    consequence, not a detail: the arc can bulge into the obstacle even when the
    straight segment was clear.
  - The design must therefore SAMPLE each arc and test every sample against the
    obstacle. An arc that collides is reported as a collision - loudly, in the
    UI and on stdout - and is never silently accepted or silently smoothed away.
  - THE FINAL-TIME VALUE IS THE TOTAL for the whole path, start to goal. Each
    segment receives a share proportional to its length, and its trapezoid is
    scaled to fit that share. Velocity and acceleration are outputs, not inputs.
  - Robot dynamics and kinematics are explicitly OUT OF SCOPE. No mass, no
    inertia, no wheel model, no steering limit.

Display, using matplotlib
  - The grid, the obstacle as a solid black 3 x 3 block, the planned path in
    green, and the robot's travelled trajectory in red, drawn in real time as
    the robot moves.
  - Below the robot, a live readout of the current r(t) and angle(t).
  - A SECOND axes in the same window plotting velocity against time, drawn
    progressively as the simulation advances - the curve grows with the red
    trajectory rather than being shown complete from the start.
      * Plot the two COMMANDED velocities, d(r)/dt and d(angle)/dt. Because each
        follows a trapezoidal profile, each appears on screen AS a trapezoid,
        one per path segment. Seeing that shape is the point of the plot.
      * Also plot the resulting Cartesian speed, sqrt(rdot^2 + (r * angledot)^2).
        It is NOT a trapezoid, and the contrast between the commanded profiles
        and the speed they produce is worth showing.
      * Label the axes with units and give the three curves a legend.
  - Resizing the window rescales all content so it always fits; nothing is
    clipped, the grid stays square, and both axes remain readable.

Controls, in one row along the bottom of the window
  - Button: compute the path with obstacle avoidance.
  - Button: start the simulation.
  - Button: stop.
  - Immediately right of Stop, a rectangle showing elapsed simulation time at
    0.1 second resolution.
  - A text input for the final time, defaulting to 5 seconds.

=== ENVIRONMENT AND CONSTRAINTS ===

  - Python 3. Third-party libraries: matplotlib and numpy ONLY. Buttons and the
    text box come from matplotlib.widgets. No tkinter, no PyQt, no other GUI
    toolkit, no path-planning or robotics library - Theta* and the trapezoidal
    profiles are written for this project.
  - NO HARDCODED VALUES. Grid size, cell size, obstacle position and extent,
    start and goal cells, default final time, colours, sampling resolution,
    figure size and every tolerance live in a config.json that the code reads at
    run time. A pure mathematical constant is not configuration.
  - Every source file has a matching test under tests/, written in the SAME step
    as the code. A step whose code exists and whose test does not is not done.
  - Every test asserts at least one failure path, not only the happy path.
  - Every function carries a header giving Purpose, Inputs, Outputs, and Raises
    where it raises.

=== THE PLAN DECOMPOSITION ===

Use exactly these seven plans, in this order. Each produces one module and its
test, which is what keeps a plan inside its token ceiling. Note that rendering
is split across two plans: the map view and the velocity view together would
exceed `ceilings["code_file_output"]` for one file.

  plan1.md  config.json + the world model: grid, cell geometry, the obstacle,
            and the conversion between grid (x,y), continuous (x,y) and polar
            (r, angle) about the bottom-left corner.
            -> world.py, tests/test_world.py

  plan2.md  Theta* path planning on the grid, returning waypoints from start to
            goal that avoid the obstacle, including the line-of-sight test that
            distinguishes Theta* from A*.
            -> planner.py, tests/test_planner.py

  plan3.md  The trapezoidal profile: given a start value, an end value and a
            duration, produce value(t) with accelerate / cruise / decelerate
            phases. Plus the allocation of the total final time across segments
            in proportion to their length.
            -> trajectory.py, tests/test_trajectory.py

  plan4.md  Arc sampling and collision verification: for each segment, drive
            r(t) and angle(t) by their own trapezoids, sample the resulting arc,
            convert each sample to a grid cell, and report any sample that
            enters the obstacle.
            -> arcs.py, tests/test_arcs.py

  plan5.md  The map view: the grid, the black obstacle, the green path, the red
            travelled trajectory, the robot triangle oriented along its motion,
            the r/angle readout, and the resize behaviour that rescales content
            to fit.
            -> render_map.py, tests/test_render_map.py

  plan6.md  The velocity view: a second axes plotting d(r)/dt, d(angle)/dt and
            the resulting Cartesian speed against time, growing as the
            simulation advances, with units, a legend and axis limits that
            follow the data.
            -> render_velocity.py, tests/test_render_velocity.py

  plan7.md  The application: the four controls, the elapsed-time display at 0.1
            second resolution, the animation loop that advances simulated time
            and redraws BOTH axes, and the wiring of everything above.
            -> app.py, tests/test_app.py

=== FILE FORMATS ===

spec.md
  What is being built, the world, the coordinate convention, the three settled
  decisions above, the library constraints, and the definition of done. It is
  re-read on EVERY call, so it must be complete and must not grow. No task list.

progress.md
  One "## plan<N>.md" section per plan, each holding that plan's checkboxes and
  nothing else. It is a task list that POINTS AT the plans; it never restates
  them. Marks, and only these three:
      - [ ]  not done
      - [x]  done: code written, test written, test passing, audit found nothing
      - [!]  audit raised an issue; add ONE line naming it
  Keep it under `ceilings["progress.md"]` for the whole project, so as plans
  finish, compress their sections to one summary line each.

plan<N>.md
  Numbered steps. EVERY step names the file it creates or changes - a step that
  names no file cannot be executed. State what "done" means for each step in
  terms a test can check.

=== THE PER-PLAN LOOP THE HARNESS RUNS ===

Write the plans knowing this is what happens to each one:

  1. The local model executes the plan, writing code and tests.
  2. The harness runs the test suite.
  3. A DIFFERENT model audits the code read-only and writes findings to audit.md.
  4. If the audit reopens steps, the plan runs once more.
  5. The plan is marked [x] if it succeeded, or [!] if the audit found an issue.
  6. The context is dropped, and the next plan begins from a blank slate.

Write nothing that depends on a human being present.
```

---

## What to look at in the classroom

- **Where the token ceilings changed the design.** The seven-plan split is not an
  aesthetic choice; it is what 4 000 tokens of new code per file forces.
- **The arc-versus-straight-line consequence.** Theta* guarantees a clear
  straight line, and polar trapezoids do not travel in straight lines. Spotting
  that before the run is worth more than any amount of debugging after it.
- **What the prompt refuses to leave open.** Polar origin, arc verification and
  the meaning of the final time are stated as decisions. Each had a plausible
  alternative that fails only hours in.
- **The dropped context.** Every instruction about naming files, and the ban on
  "as decided earlier", exists because plan 4 cannot see plan 3.
