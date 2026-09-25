# Example plan set - mobile robot path planner

**Goal.** Show what a plan set that fits the token ceilings actually
looks like, so the shape can be copied rather than guessed at.

**Contents.** The nine documents produced by the prompt in
`../robot-planning-prompt.md`, and nothing else. No code: the local model
writes that overnight from these.

## To run this example

```powershell
# 1. the project, which gets its own .venv
.\new-project.ps1 -Name robot-planner -Root "$HOME\projects"

# 2. the example's only third-party dependencies, into THAT .venv
& "$HOME\projects\robot-planner\.venv\Scripts\python.exe" -m pip install matplotlib numpy

# 3. the documents, replacing the templates
Copy-Item "$HOME\.config\aider\examples\robot-planner-plans\*.md" `
          "$HOME\projects\robot-planner\docs\superpowers\plans\" -Force
Remove-Item "$HOME\projects\robot-planner\docs\superpowers\plans\README.md"

# 4. dry-run first, then drop -DryRun to run the night
cd "$HOME\projects\robot-planner"
aider-plan.ps1 -DryRun -TestCommand '.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"'
```

**Step 2 is not optional.** `new-project.ps1` creates an EMPTY `.venv`,
and `spec.md` declares matplotlib and numpy as this example's only
permitted third-party libraries. Without them the suite fails on `import`
before the model has written a line, and that failure reads as the model's
fault rather than as a missing install.

## Sizes, against their ceilings

| File | Tokens | Ceiling |
|---|---:|---:|
| spec.md | 1397 | 4000 |
| progress.md | 457 | 2048 |
| plan1.md to plan7.md | 526 to 664 each | 4000 |

Every one is well inside its budget. That is the point: the seven-plan
split is what keeps each plan, and the code it asks for, inside the
ceilings. A plan that does not fit is not a long plan, it is two plans.
