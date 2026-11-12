# Spec - the dispatch guard and the kit script sync

`local-coder` runs ONE plan on the aider kit. The kit's scripts are installed in `~/.local/bin` and its
configuration in `~/.config/aider`. Two pieces of this repository still assume the old design and are
changed here: the hook that judges a `local-coder` dispatch, and the sync that keeps the installed scripts
current.

## Guard

`.claude/hooks/local-coder-dispatch-guard.py` stops asking the resolver for a role. It checks that the
aider kit is installed: the folder `~/.config/aider` holds `model-settings.yml` and
`context-budget.json`, and the folder `~/.local/bin` holds `aider-plan.ps1`. These two folders and the
list of three file names are configuration of the guard (R0, R4 with provenance), with `~` expanded. A
missing file is a refusal that names it and says to run the kit installer. Every other behaviour is
unchanged: the plan header and size checks, the executor must be `local-coder`, and R11 (any failure
of the hook itself exits 0 in silence).

## Sync of the kit scripts

No script copies only the kit scripts: the kit installer works file by file and its force option would also
overwrite the owner's tuned configuration. The existing repository sync, run at every session start by the
sync option of the junction installer, is extended instead. A new function in `scripts/lib/rt-sync.ps1`
copies every file at the top level of `.claude/skills/aider-setup/scripts` (not the `Test` folder) into the
`.local/bin` folder of the home that owns the `.claude` folder being synced. Rules:

- The installed text is the repository text with every `{{HOME}}` replaced by that home path written with
  forward slashes, saved as UTF-8 without a byte order mark (the same rule as the kit installer). A file
  whose installed text is already identical is left alone.
- A file is written only when it is proven: a script must parse without errors, a Python file must be
  proven by the green stamp (`Test-RtProven`), a data file must parse as JSON, a batch file has no check.
  A file that fails is reported as held and never written.
- Before a write, the previous installed file is copied into the undo folder, as `Sync-RtFile` does.
- The `.local/bin` folder must already exist: when it does not, the step is skipped without a message (the
  kit is not installed, rule R11). The `.config/aider` folder is never read or written.
- The step honours the dry-run flag already used by the sync (`RtWhatIf`): it reports and writes nothing.

## Language and conventions

- **Language and version:** Python 3.11 (standard library only) for the hook and its test; Windows PowerShell 5.1
  for the sync step and its check script.
- **Case of names:** Python functions are `verb_complement` in lower snake case, constants `UPPER_SNAKE_CASE`;
  PowerShell functions are `Verb-Noun` with an approved verb.
- **Documentation comment:** a docstring (Python) or a comment block (PowerShell) with Purpose, Inputs, Outputs
  and, when it raises on purpose, Raises.
- **Types:** a type annotation on every Python parameter and return value.
- **Tests:** the hook test is a `unittest` file in `.claude/hooks/Test/`, run as a script. The sync check is the
  PowerShell script `scripts/test/verify-sync-writes.ps1`, which exits non-zero on a failure.
- **Format and lint:** none required.
