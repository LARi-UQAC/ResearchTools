# Spec - cube move notation

**Goal.** A small pure-Python module that reads, writes and inverts Rubik cube move notation. It is the fixture
of the single-plan live test of the aider kit.

**Purpose of the fixture.** It tests the kit, not the model. The task is deliberately easy and deterministic so
that the local model passes on its first or second try and the run reaches the audit. Nothing here is a
capability test: no cube geometry, no permutation table, no search.

**Contents.** The decisions the plan relies on. Nothing else.

## Decisions

- A move is one of the face letters `U D L R F B`, optionally followed by an apostrophe (counter-clockwise turn)
  or the digit 2 (half turn). Examples: `R`, `U'`, `F2`.
- A sequence is a list of moves in the order they are played. In text, moves are separated by single spaces.
- An unknown token raises `ValueError` naming the token.
- No third-party package, no file, no printing. Python standard library only.

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

- Source in `scripts/`, one module `scripts/moves.py`.
- Tests in their own file in the `Test` folder beside the source: `scripts/Test/test_moves.py`. A test file never
  lives inside the module.
