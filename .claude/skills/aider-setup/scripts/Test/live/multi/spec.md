# Spec - grid path length and trapezoid speed, two independent modules

**Goal.** Two small pure-Python modules for a point robot, with no simulated world and no robot model. They are
the fixture of the multi-plan live test of the aider kit: two plans, each with its own module and its own test
file, run one after the other in one kit run.

**Purpose of the fixture.** It tests the kit, not the model. Both tasks are deliberately easy, closed-form and
deterministic so that the local model passes quickly and every plan reaches its audit. Nothing here is a capability
test: no search algorithm, no optimisation.

**Contents.** The decisions both plans rely on. Nothing else.

## Decisions

- A grid is a list of rows of 0 (free) and 1 (obstacle); a cell is a `(row, column)` pair of integers.
- Plan 1 gives two building blocks of any-angle path planning: whether two cells see each other across free
  cells, and the length of a path through waypoints.
- Plan 2 gives the speed along one straight segment with a trapezoid profile: constant acceleration up to a maximum
  speed, cruise, constant deceleration to a stop. When the segment is too short to reach the maximum speed the
  profile is a triangle.
- No third-party package, no file, no printing. Python standard library only.
- The two modules do not import each other.

## Language and conventions

- **Language and version:** Python 3.11 or later, standard library only.
- **Case of names:** functions are `verb_complement` in lower snake case (`parse_moves`), private helpers
  start with an underscore, classes are `PascalCase`, constants are `UPPER_SNAKE_CASE`, variables are
  lower snake case.
- **Documentation comment:** a docstring with the parts Purpose, Inputs, Outputs and, when the function
  raises on purpose, Raises.
- **Types:** a type annotation on every parameter and every return value.
- **Tests:** `unittest`, in the folder `Test` beside the source, one file `test_<module>.py` per module.
  Each test file ends with `unittest.main()` and puts the parent folder of its own folder at the start of
  `sys.path` before it imports the module.
- **Format and lint:** none required here.

## Layout

- Sources in `scripts/`: `scripts/grid_path.py` (plan 1) and `scripts/trapezoid.py` (plan 2).
- Each module has its own test file in the `Test` folder beside the sources: `scripts/Test/test_grid_path.py` and
  `scripts/Test/test_trapezoid.py`. A test file never lives inside a module.
