# Coding rules

These rules bind every file you write. Follow them exactly.

Rules: 26 (R0-R105)

---

**R0 - no numeric literal in code.** In a function body the only numbers allowed are 0, 1, 2 and -1.
Every threshold, limit, timeout, tolerance, size, count, retry number, port and default parameter
value, and every exponent other than 2 (use the language's square-root function, never a fractional
power), comes from a configuration file read at run time, through a key whose name carries its unit
(`timeout_s`). A constant at the top of a module is not configuration. Numbers inside a test fixture
and unit conversion factors may stay. If no source gives the value, put the key in the configuration
with the provenance "unspecified" and mark the step `- [!]` with one line saying so. Never invent a default.

**R1 - no hardcoded path.** An absolute path, an output folder or a program location comes from an
environment variable or the configuration file. A path built from the module's own location is fine.

**R2 - one owner for each external identifier.** A model name, an API host, a service address or a file
format version is written once, in the configuration. Every other place reads it.

**R3 - a missing configuration value is an explicit error.** The message names the key and the file
it was expected in. Never a silent default and never a weaker substitute.

**R4 - a numeric key states its unit and its provenance.** `timeout_s` says what it counts. Next to
the value, say where it comes from: measured (tool and date), specified (document), or chosen (by whom).

**R5 - an enum-like string comes from one table.** A mode, a status or a role is defined once, as a
named constant or the language's enumeration type, and used from there. A string repeated in several
places is a typo waiting to happen.

**R6 - a list of literals is data.** A mapping, a keyword table or a prompt text lives in a data file
the code reads. The code holds the logic only.

**R8 - no silent fallback.** A missing dependency, key or input stops the run with a message that
names it. Never swallow an error: no empty error handler, no ignored result, no catch-all that
neither re-raises nor reports. Never return a weaker result without saying so.

**R9 - verify the effect, not the return code.** After writing a file or changing a state, read back
what should have changed and fail if it did not.

**R10 - every network call and subprocess call has a timeout and a bounded retry count.** Both
values come from the configuration (R0). No unbounded wait, no unbounded loop.

**R12 - exit codes mean something.** 0 is success, 2 is a refusal by design (bad arguments, missing
input), any other non-zero is a failure. The module header states it.

**R14 - use only what exists.** Call only functions, options and modules that exist in the standard
library, in a declared dependency or in this project. Never invent a name, a flag or a file.

**R16 - a program that changes state offers `--dry-run`.** It prints what it would do and changes
nothing. A destructive action also requires `--yes`.

**R17 - a program that changes state also writes a machine-readable report** (JSON) beside its text.

**R19 - no wall clock and no unseeded randomness in logic.** The caller passes the time and the seed
in. The same input gives the same output on a second run.

**R20 - every test file asserts a failure path.** Wrong input, missing file or empty case, as well as
the normal case. A test that can only pass proves nothing.

**R21 - a test reads no file outside the project.** It builds the data it needs itself or reads a
fixture stored with the tests, so it gives the same result on any machine.

**R24 - confine every path derived from input.** Resolve it to its canonical absolute form first,
then check that it sits inside the allowed folder, before anything is written. Refuse otherwise,
never clamp.

**R27 - every function has a header a caller can act on.** A documentation comment, in the form the
spec names for the language, with these parts in order: `Purpose` (one or two sentences, what, not
how), `Details` (only for a subtle algorithm), `Inputs` (every parameter: name, type, meaning),
`Outputs` (type, meaning, and any side effect), `Raises` (each error the function returns or throws
and its condition, mandatory as soon as it does so on purpose). A one-line helper may carry `Purpose`
alone.

**R99 - the language and its conventions come from the spec.** The section "Language and conventions"
of `spec.md` names the language, the case of names, the form of documentation comments, the test
folder and the test command, and the format and lint commands. Follow it exactly. If it is missing,
mark the step `- [!]` and say so; do not guess a language.

**R100 - names say what a thing is or does.** A function name is a verb followed by what it acts on,
`verb_complement`, in the case the spec gives for functions: `compute_speed`, `load_config`,
`check_bounds`. A name that does not start with a verb is wrong. A private helper is marked the way the
language marks it. A variable is meaningful, never a single letter. A boolean starts with `is_`, `has_` or `can_` in the same case. A quantity carries its unit
(`speed_mps`, `delay_s`). Types, constants and variables follow the case of the spec.

**R101 - a prefix shows where a variable lives.** `g_` for a global that is reassigned, and avoid those. A parameter and a field of an
object carry no prefix. A constant has no prefix: it follows the constant case of the spec.

**R102 - every parameter and every return value has a declared type.** A statically typed language
does it in the signature. In a dynamic language, use the language's type annotations.

**R103 - comments.** A comment says WHY: a unit, a constraint, a choice that is not obvious. It never
repeats what the line does, never records your reasoning, your doubts or a draft ("wait", "let's",
"maybe", "re-read the spec"), and never keeps commented-out code. Remove such text before you
finish. No `TODO` and no placeholder body: finish the function or mark the step `- [!]`.

**R104 - code layout.** One function does one job and fits on a screen (about 40 lines). Return early
on an error instead of nesting more than three levels. Declare dependencies at the top of the file in
the language's usual way, standard library first, then third-party, then this project. None unused,
none imported by a wildcard form.

**R105 - no output from a library module.** A module that other code uses does not print and has no
effect when it is loaded. Only the program's entry point writes to the console. Use the language's
logging facility for diagnostics.
