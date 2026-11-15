"""Insert the 'create a project' and Python-environment material into the manual."""

import pathlib

p = pathlib.Path.home() / ".config/aider/MANUAL.md"
t = p.read_text(encoding="utf-8")

old_head = "## 7. Per-project layout\n"
assert old_head in t, "section 7 heading not found"

new = """## 7. Create a project

Every project is its own directory with its own git repository and **its own
Python environment**. Nothing about a project lives in the home directory.

### 7.1 Scaffold it

```powershell
.\\new-project.ps1 -Name my-project -Root C:\\path\\to\\your\\projects
```

That one command creates the directory, runs `git init` on a `work` branch,
installs the two branch-protection hooks into `.git/hooks`, writes the
`docs/superpowers/plans/` skeleton with its three template files, creates the
`Test/` directory, and writes a `.gitignore`. It refuses rather than
overwriting a directory that already exists.

`-DryRun` reports everything and creates nothing.

For a repository that already exists, install only the hooks:

```powershell
.\\install-hooks.ps1 -Path C:\\path\\to\\existing-repo
```

### 7.2 The project's Python environment

aider has its own environment, created by `uv tool install` in section 3, and
it is **not** the one your code runs in. Your project needs its own, for two
reasons: its dependencies must not mix with aider's, and the test command the
driver runs must use *your* interpreter, not whichever `python` happens to be
first on PATH.

```powershell
cd <your project>
uv venv .venv                      # or:  python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
uv pip install -r requirements.txt # if the project has one
```

If PowerShell refuses to run the activation script, allow it for the current
user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Then point the test command at that interpreter explicitly.** This matters
more than it looks: the driver runs the test command as a child process, which
does not inherit an activation done in your shell.

```powershell
-TestCommand '.\\.venv\\Scripts\\python.exe -m unittest discover -s Test -p "test_*.py"'
```

Writing `python -m unittest` instead would run whichever interpreter PATH
resolves, and a suite that passes under the wrong interpreter proves nothing.

`.venv/` belongs in `.gitignore`; `new-project.ps1` puts it there.

### 7.3 What the directory looks like

"""

t = t.replace(old_head, new, 1)

# the old section 7 body keeps its tree and hook material, minus the duplicated
# hook install instructions the scaffolder now performs
old_hooks_intro = """### Branch protection

aider commits after every successful edit. Those commits must never land on
`main`. Install the two hooks **per project** — `.git/hooks` is never committed,
so this is done once per clone and touches no global git setting:"""
new_hooks_intro = """### 7.4 Why the hooks are per repository

aider commits after every successful edit, and those commits must never land on
`main`. `new-project.ps1` installs both hooks for you; this is what they
contain, so you can check them rather than trust them. `.git/hooks` is never
committed, which is why installing them is a per-clone step:"""
if old_hooks_intro in t:
    t = t.replace(old_hooks_intro, new_hooks_intro, 1)

t = t.replace("""```powershell
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
```

A global `core.hooksPath` is **not** used""",
"""Verify them in both directions, because a guard that cannot fail proves
nothing:

```powershell
git switch main   ; git commit --allow-empty -m x    # must be REFUSED
git switch -c work; git commit --allow-empty -m x    # must SUCCEED
```

A global `core.hooksPath` is **not** used""", 1)

p.write_text(t, encoding="utf-8")
print("manual: project + python environment section inserted")
