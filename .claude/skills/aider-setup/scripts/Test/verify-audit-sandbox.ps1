<#
.SYNOPSIS
  Prove the audit pass cannot rewrite the project, by making a stub reviewer
  try exactly what the real one did.

.DESCRIPTION
  Measured 2026-09-06 on plan 5 of the night run. The reviewer emitted
  SEARCH/REPLACE blocks for three source files it had never been given; aider
  added each of them to the chat by itself, because --yes answers that prompt
  as well; it applied the edits and committed them. audit.md stayed at 235
  bytes and the plan was recorded as unaudited.

  The driver's comment claimed "the only file it can act on is audit.md". That
  was an assumption about the model's motive, not a property of the harness,
  and this suite exists because the difference cost a night.

  No model runs here. A stub `aider` is placed first on PATH and does what the
  real reviewer did: append to the audit report it was given, AND reach out to
  rewrite a source file in the project by absolute path. Two things are then
  asserted: the project file is unchanged, and the driver SAID that it caught
  the attempt.

  The second half is the negative control, and it is the half that matters: a
  guard whose message nobody has ever seen is indistinguishable from a guard
  that cannot fire.
#>
[CmdletBinding()]
param(
    [string]$Driver = ""
)

$ErrorActionPreference = "Stop"
if ($Driver -eq "") {
    $Driver = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) "aider-plan.ps1"
}

$passed = 0
$failed = 0
function Check([string]$label, [scriptblock]$body) {
    $why = & $body
    if ($why) { Write-Host ("  FAIL  " + $label + " - " + $why) -ForegroundColor Red; $script:failed++ }
    else      { Write-Host ("  ok    " + $label) -ForegroundColor Green; $script:passed++ }
}

$root = Join-Path $env:TEMP ("audit-sandbox-test-" + (Get-Date -Format "HHmmssfff"))
$proj = Join-Path $root "project"
$stub = Join-Path $root "stub"
New-Item -ItemType Directory -Force -Path $proj, $stub, (Join-Path $proj "tests"),
                                     (Join-Path $proj "docs\superpowers\plans") | Out-Null

# --- a project that looks like a night in progress -------------------------
$plans = Join-Path $proj "docs\superpowers\plans"
Set-Content -LiteralPath (Join-Path $proj "widget.py") -Value "VALUE = 1" -Encoding ascii
Set-Content -LiteralPath (Join-Path $proj "tests\test_widget.py") -Encoding ascii -Value @(
    "import unittest"
    "class T(unittest.TestCase):"
    "    def test_one(self):"
    "        self.assertEqual(1, 1)"
)
Set-Content -LiteralPath (Join-Path $plans "spec.md")     -Value "# Spec"     -Encoding ascii
Set-Content -LiteralPath (Join-Path $plans "audit.md")    -Value "# Audit"    -Encoding ascii
Set-Content -LiteralPath (Join-Path $plans "progress.md") -Encoding ascii -Value @(
    "# Progress"
    ""
    "## plan1.md"
    "- [ ] widget.py"
)
Set-Content -LiteralPath (Join-Path $plans "plan1.md") -Value "Edit widget.py" -Encoding ascii

Push-Location $proj
& git init --quiet 2>&1 | Out-Null
& git config user.email "t@local" | Out-Null
& git config user.name  "t"       | Out-Null
& git checkout -q -b work 2>&1 | Out-Null
& git add -A 2>&1 | Out-Null
& git commit -q -m seed 2>&1 | Out-Null
Pop-Location

$original = Get-Content -LiteralPath (Join-Path $proj "widget.py") -Raw

# --- the stub reviewer -----------------------------------------------------
# Call 1 is the writer: it changes the source, so the driver has something to
# audit. Call 2 is the reviewer: it appends to the report it was handed AND
# rewrites a project file by absolute path, which is the trespass.
$counter = Join-Path $root "calls.txt"
$stubBody = @(
    '@echo off'
    "set C=$counter"
    ':: The driver asks aider which model it would use, by running it with'
    ':: --exit and reading a "Main model:" line off its output. A stub that'
    ':: does not answer that probe makes the driver REFUSE before the audit is'
    ':: ever reached, which is how this suite first reported a guard failure'
    ':: that was really a fixture failure.'
    'echo %* | findstr /C:"--exit" >nul && ( echo Main model: ollama_chat/qwen3.8-aider & exit /b 0 )'
    'if not exist "%C%" ( echo 1> "%C%" & goto WRITER )'
    'goto REVIEWER'
    ':WRITER'
    ('echo VALUE = 2 > "' + (Join-Path $proj "widget.py") + '"')
    'exit /b 0'
    ':REVIEWER'
    ':: The report goes to the audit.md in the CURRENT directory, which is what'
    ':: a real reviewer writes: the file it was handed. Writing to the project'
    ':: copy instead made the fixture test the fixture - the driver copies the'
    ':: sandbox report back over it, so the report looked lost.'
    'echo ## plan1.md >> "%CD%\audit.md"'
    ('echo TRESPASS = 1 > "' + (Join-Path $proj "widget.py") + '"')
    'exit /b 0'
)
Set-Content -LiteralPath (Join-Path $stub "aider.cmd") -Value $stubBody -Encoding ascii

# The stub writes to the REAL audit.md rather than to the sandbox copy on
# purpose: the point under test is the project guard, and writing the report
# where the driver expects it keeps the run moving to that guard.

# -Model rather than -Config: resolving from a config makes the driver ask
# aider itself, and aider here is the stub, so the answer came back empty and
# the run was refused before the audit was ever reached.
#
# The tag is a REAL registered one, and that is not laziness. Get-ModelWindow
# imports aider's own Model() to read max_input_tokens, so an invented tag
# resolves to no window and the run is refused at the budget stage. No model is
# ever loaded: the stub intercepts every aider call, and only the metadata
# lookup touches anything real.

$env:PATH = $stub + ";" + $env:PATH
$out = ""
try {
    # -Path, not -Project. The driver takes the project as -Path and there is
    # no -Project parameter at all; passing one makes PowerShell refuse the
    # whole call before a line of the driver runs, which is exactly how this
    # suite first reported three green-looking failures with the stub never
    # invoked.
    $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $Driver `
              -Path $proj `
              -Model "ollama_chat/qwen3.8-aider" `
              -TestCommand "python -m unittest discover -s tests -p test_*.py" `
              2>&1 | Out-String
} catch {
    $out = $_ | Out-String
}

$after = ""
if (Test-Path -LiteralPath (Join-Path $proj "widget.py")) {
    $after = Get-Content -LiteralPath (Join-Path $proj "widget.py") -Raw
}

Write-Host ""
Write-Host "== the reviewer must not be able to rewrite the project ==" -ForegroundColor Cyan

Check "the trespass never survives in the project" {
    if ($after -match "TRESPASS") { return "widget.py still holds the reviewer's edit" }
    $null
}

Check "the driver SAYS it caught the attempt" {
    if ($out -notmatch "REVIEWER (TOUCHED|COMMITTED)") {
        return "no guard message in the run output, so a silent guard cannot be told from a broken one"
    }
    $null
}

Check "the report the reviewer wrote is kept" {
    $a = Get-Content -LiteralPath (Join-Path $plans "audit.md") -Raw
    if ($a -notmatch "plan1") { return "audit.md lost the reviewer's own output while the trespass was undone" }
    $null
}

Check "NEGATIVE CONTROL: the stub really did attempt it" {
    if (-not (Test-Path -LiteralPath $counter)) { return "the stub never ran, so nothing above was tested" }
    $null
}

Write-Host ""
Write-Host ("passed {0}, failed {1}" -f $passed, $failed)
Write-Host ("workspace: {0}" -f $root) -ForegroundColor DarkGray
exit ([int]($failed -gt 0))
