"""Bring the manual into agreement with the files the kit actually ships.

SUPERSEDED 2026-09-05, and kept only as the record of what it patched.
MANUAL.md was rewritten that day into numbered steps, so not one of the
anchors below still exists in it - the first `sub()` call alone asserts on
"## 1. What this builds". Running this fails loudly rather than corrupting
the manual, which is the one good thing about assert-based patching, but it
cannot do anything useful either. Edit MANUAL.md directly.
"""

import pathlib

p = pathlib.Path.home() / ".config/aider/MANUAL.md"
t = p.read_text(encoding="utf-8")
changes = []


def sub(old, new, label):
    global t
    assert old in t, f"NOT FOUND: {label}"
    t = t.replace(old, new, 1)
    changes.append(label)


# --- A. a quick path, so the kit's scripts are found before the long form ----
sub(
    "---\n\n## 1. What this builds\n",
    """---

## 0. The short path

The kit does most of sections 3 to 7 for you. Read them anyway - they say what
each file is for and why each number is what it is - but this is the order:

```powershell
# once per machine
uv tool install --force --python python3.12 --with pip aider-chat@latest
ollama pull qwen3.8:latest
ollama pull gemma4:31b-maxctx
.\\setup.ps1 -DryRun          # see what it would write
.\\setup.ps1                  # write the configuration into your home

# once per project
.\\new-project.ps1 -Name my-project -Root C:\\path\\to\\your\\projects 
```

Then set the Ollama variables from section 2, write your `spec.md` and
`plan1.md`, and run the driver from section 11.

`setup.ps1` replaces every `{{HOME}}` placeholder in the kit's files with your
own home directory. Where this manual shows `{{HOME}}`, read it as the copy
installed on your machine already naming your real path.

---

## 1. What this builds
""",
    "section 0 (short path)",
)

# --- B. section 5 must say the installer writes these files -----------------
sub(
    """Five files. One sits at the home root because aider finds it by name; the rest
live together in `~/.config/aider/`.""",
    """Five files. One sits at the home root because aider finds it by name; the rest
live together in `~/.config/aider/`.

**`setup.ps1` writes all five for you** - this section exists so you know what
they contain and can check them, not so you type them. The installer adds and
never silently replaces: a file that already exists is kept, and reported as
kept, unless you pass `-Force`. `-DryRun` names every path it would write and
writes nothing.""",
    "section 5 (installer writes the files)",
)

# --- C. the test command must use the project's own interpreter -------------
sub(
    """The test command is **supplied by you and never guessed**:

```powershell
-TestCommand 'python -m unittest discover -s Test -p "test_*.py"'
```""",
    """The test command is **supplied by you and never guessed**, and it names the
project's own interpreter rather than whatever PATH resolves - see section 7.2:

```powershell
-TestCommand '.\\.venv\\Scripts\\python.exe -m unittest discover -s Test -p "test_*.py"'
```""",
    "section 9 (venv interpreter)",
)

t = t.replace(
    """  -TestCommand 'python -m unittest discover -s Test -p "test_*.py"'""",
    """  -TestCommand '.\\.venv\\Scripts\\python.exe -m unittest discover -s Test -p "test_*.py"'""",
)
changes.append("section 11 (venv interpreter, both invocations)")

# --- D. verification should start with the installer's own dry run ----------
sub(
    """```powershell
# the model actually resolved, and the whole budget, without starting a model
aider-plan.ps1 -DryRun -Config ... -BudgetFile ... -TestCommand '...'""",
    """```powershell
# what the installer would write, before it writes anything
.\\setup.ps1 -DryRun

# what the scaffolder would create, before it creates anything
.\\new-project.ps1 -Name probe -Root C:\\path\\to\\your\\projects -DryRun

# the model actually resolved, and the whole budget, without starting a model
aider-plan.ps1 -DryRun -Config ... -BudgetFile ... -TestCommand '...'""",
    "section 12 (dry runs of the installers)",
)

# --- E. name every file the kit ships ---------------------------------------
sub(
    """## 14. What is deliberately not automated""",
    """## 13.5 What the kit ships

| Path | What it is |
|---|---|
| `README.md` | the one-page version of section 0 |
| `MANUAL.md` | this file |
| `setup.ps1` | installs the configuration for the current user |
| `new-project.ps1` | scaffolds one isolated project |
| `install-hooks.ps1` | adds the hooks to a repository you already have |
| `config/aider.conf.yml` | the one file aider finds by name |
| `config/model-settings.yml` | per-model settings for both tags |
| `config/conventions.md` | the working protocol, read on every call |
| `config/rules.md` | the coding rules, generated |
| `config/context-budget.json` | every token figure, with its provenance |
| `bin/aider-plan.ps1` | the driver |
| `bin/aider-rules-sync.py` | regenerates `rules.md` from a rules directory |
| `git-hooks/pre-commit`, `pre-push` | per-repository branch protection |
| `project-template/` | the three files a project starts from |

---

## 14. What is deliberately not automated""",
    "section 13.5 (kit inventory)",
)

p.write_text(t, encoding="utf-8")
for c in changes:
    print("  fixed:", c)
