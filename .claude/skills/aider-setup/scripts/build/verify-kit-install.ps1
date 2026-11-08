<#
.SYNOPSIS
  Install the assembled kit into a scratch home and prove it starts there.

.DESCRIPTION
  The gate that publishing goes through. It exists because of one measurement:
  on 2026-09-04 the kit had been published three times, and every static check
  was green - the PowerShell parser, the JSON parse, the leak scan with its
  negative control, the driver's 33 offline checks, and two complete three-hour
  nights - while setup.ps1 wrote a config that aider REFUSED to read. PowerShell
  5.1's `Set-Content -Encoding UTF8` emits a byte order mark, and aider's YAML
  parser answers "did not find expected <document start>". The kit's own copy of
  the file was byte-perfect; only the INSTALLED copy was broken, so nothing that
  inspected the artefact could ever have found it.

  So this script does not inspect. It installs, and then it runs.

  Six checks, and the last one is the point:

    1. the four build scripts produce an assembled kit          (skipped with -Kit)
    2. every PowerShell file parses, every JSON parses, every
       Python file compiles - with ast.parse, never py_compile,
       which writes __pycache__ beside its target and put three
       .pyc files into two published kits
    3. the assembled tree matches, file by file, the manifest the
       build DECLARES it will ship - and holds no .pyc anywhere
    4. setup.ps1 installs into a scratch home and exits 0
    5. no {{HOME}} placeholder and no BOM survives in ANY
       installed file
    6. the driver, RUN FROM THAT INSTALLATION, completes a dry
       run with exit 0

  Nothing outside $env:TEMP is written, and the real home is never touched:
  setup.ps1 is invoked with -HomeDir, which is the reason that parameter exists.

.PARAMETER Kit
  An already-assembled kit directory. Omitted, the four build scripts are run
  into a fresh temporary directory first.

.PARAMETER Report
  Write a machine-readable JSON report here as well as the human text (R17).

.PARAMETER KeepScratch
  Leave the scratch home, the assembled kit and the fixture on disk for
  inspection. They are deleted otherwise.

.EXAMPLE
  .\verify-kit-install.ps1
  .\verify-kit-install.ps1 -Kit C:\Temp\kit-123 -Report C:\Temp\gate.json
#>
[CmdletBinding()]
param(
    [string]$Kit = "",
    [string]$Report = "",
    [switch]$KeepScratch
)

$ErrorActionPreference = "Stop"

$buildDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# Sibling-first: the A/B harness lives one level up from build/ once this
# gate runs from inside ResearchTools. $HOME stays the fallback for a
# standalone checkout with no repository around it.
$abHarness = Join-Path (Split-Path $buildDir -Parent) "aider-ab.ps1"
if (-not (Test-Path -LiteralPath $abHarness)) {
    $abHarness = Join-Path $HOME ".local\bin\aider-ab.ps1"
}

$script:results = @()
$script:failures = 0

function Check([string]$name, [scriptblock]$body) {
    # A check returns $true, or a string saying what it found. Never a bare
    # $false: a gate that reports "check 5 failed" and nothing else costs the
    # reader the whole investigation the gate was supposed to have done.
    $detail = ""
    $ok = $false
    try {
        $r = & $body
        if ($r -is [string]) { $detail = $r }
        elseif ($r) { $ok = $true }
    } catch {
        $detail = $_.Exception.Message
    }
    if ($ok) {
        Write-Host ("  ok    {0}" -f $name) -ForegroundColor Green
    } else {
        Write-Host ("  FAIL  {0}" -f $name) -ForegroundColor Red
        if ($detail -ne "") { Write-Host ("        {0}" -f $detail) -ForegroundColor Red }
        $script:failures++
    }
    $script:results += [pscustomobject]@{ check = $name; ok = $ok; detail = $detail }
}

# --- 1. an assembled kit ----------------------------------------------------
$builtHere = $false
if ($Kit -eq "") {
    $Kit = Join-Path $env:TEMP ("gate-kit-" + [guid]::NewGuid().ToString("N").Substring(0,8))
    $builtHere = $true
    Write-Host "== Building the kit =="
    $conf = Join-Path $buildDir "aider.conf.yml.saved"
    if (-not (Test-Path -LiteralPath $conf)) {
        Write-Host "REFUSED: $conf is missing, so the kit cannot be assembled." -ForegroundColor Red
        exit 2
    }
    # Every redirection inside cmd. PowerShell 5.1 wraps a native command's
    # stderr in an ErrorRecord and $ErrorActionPreference = "Stop" then kills the
    # script - measured four times in this pipeline, most recently on a git
    # WARNING that meant nothing was wrong.
    & cmd /c "python `"$buildDir\build_kit.py`" `"$Kit`" `"$conf`" 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "REFUSED: build_kit.py exited $LASTEXITCODE. Nothing else was run." -ForegroundColor Red
        exit 1
    }
    foreach ($step in @("finish_kit.py", "newproject_ps1.py", "patch_setup.py")) {
        $null = & cmd /c "python `"$buildDir\$step`" `"$Kit`" 2>&1"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "REFUSED: $step exited $LASTEXITCODE." -ForegroundColor Red
            exit 1
        }
    }
} elseif (-not (Test-Path -LiteralPath $Kit)) {
    Write-Host "REFUSED: -Kit $Kit does not exist." -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "== The assembled kit: $Kit =="

# --- 2. everything the kit ships must at least be readable by its own tools --
Check "every PowerShell file in the kit parses" {
    $bad = @()
    foreach ($f in (Get-ChildItem -LiteralPath $Kit -Recurse -File -Filter *.ps1)) {
        $e = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$null, [ref]$e)
        if ($e.Count -ne 0) { $bad += ("{0}: {1}" -f $f.Name, $e[0].Message) }
    }
    if ($bad.Count -eq 0) { $true } else { $bad -join "; " }
}

Check "every JSON file in the kit parses" {
    $bad = @()
    foreach ($f in (Get-ChildItem -LiteralPath $Kit -Recurse -File -Filter *.json)) {
        try { $null = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { $bad += $f.Name }
    }
    if ($bad.Count -eq 0) { $true } else { "unparsable: " + ($bad -join ", ") }
}

Check "every Python file in the kit compiles" {
    # ast.parse, deliberately, never py_compile: py_compile writes a .pyc BESIDE
    # its target even under -B, and that is how __pycache__ reached two published
    # kits on 2026-09-03. This checks syntax and writes nothing.
    $bad = @()
    foreach ($f in (Get-ChildItem -LiteralPath $Kit -Recurse -File -Filter *.py)) {
        $out = & cmd /c "python -c `"import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())`" `"$($f.FullName)`" 2>&1"
        if ($LASTEXITCODE -ne 0) { $bad += ("{0}: {1}" -f $f.Name, ($out | Select-Object -Last 1)) }
    }
    if ($bad.Count -eq 0) { $true } else { $bad -join "; " }
}

# --- 3. the whole-artefact invariants ---------------------------------------
Check "the assembled tree matches what the build declared" {
    # Declared against on-disk, never tree against tree. A leaked file - the
    # __pycache__ artefacts that reached two published kits - is present in the
    # tree and absent from the declaration, so this difference names it, while a
    # walk of the tree compared with itself would pass for ever. The literal
    # count this replaced rotted three times (31, then 50, then 52) and said only
    # "found 33, expected 31", which cost two rounds to turn into two filenames.
    $mf = $Kit + ".declared"
    if (-not (Test-Path -LiteralPath $mf)) {
        # Deliberately a failure rather than a fallback to counting the tree: a
        # kit with no declaration cannot be verified this way, and a gate that
        # quietly weakened itself here is the one that would pass for ever (R8).
        return "no declaration beside the kit at $mf (build_kit.py writes <kit>.declared, NOT the published <kit>.zip.manifest, which is the recipient copy) - re-run the four build steps"
    }
    $declared = @(Get-Content -LiteralPath $mf -Encoding UTF8 |
                  ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
    $root = (Resolve-Path -LiteralPath $Kit).ProviderPath.TrimEnd('\\')
    $onDisk = @(Get-ChildItem -LiteralPath $Kit -Recurse -File -Force |
                ForEach-Object { $_.FullName.Substring($root.Length + 1) })
    $leaked  = @($onDisk   | Where-Object { $declared -notcontains $_ })
    $missing = @($declared | Where-Object { $onDisk   -notcontains $_ })
    if ($leaked.Count -eq 0 -and $missing.Count -eq 0) { return $true }
    $parts = @()
    if ($leaked.Count  -gt 0) { $parts += "on disk, never declared: "  + ($leaked  -join ", ") }
    if ($missing.Count -gt 0) { $parts += "declared, not on disk: "     + ($missing -join ", ") }
    $parts -join " | "
}

Check "every PowerShell block in the shipped manual parses" {
    # The manual is shipped INSTRUCTIONS, so its commands are part of the
    # artefact and belong in the gate. Two blocks used to fail here, on angle-
    # bracket placeholders that PowerShell reads as the reserved "<" operator:
    # a reader copying them verbatim met a parser error, which reads as the kit
    # being broken rather than as a value they were meant to substitute. They
    # are quoted now, so every block parses and this check has teeth.
    $manual = Join-Path $Kit "MANUAL.md"
    if (-not (Test-Path -LiteralPath $manual)) { return "no MANUAL.md in the kit" }
    $text = Get-Content -LiteralPath $manual -Raw -Encoding UTF8
    $blocks = [regex]::Matches($text, "``````powershell?
(.*?)``````",
                               [System.Text.RegularExpressions.RegexOptions]::Singleline)
    if ($blocks.Count -eq 0) { return "no powershell blocks found, so this check proves nothing" }
    $bad = @()
    foreach ($b in $blocks) {
        $e = $null
        $null = [System.Management.Automation.Language.Parser]::ParseInput(
                    $b.Groups[1].Value, [ref]$null, [ref]$e)
        if ($e.Count -ne 0) {
            $first = ($b.Groups[1].Value -split "?
")[0]
            $bad += ("{0} -> {1}" -f $first, $e[0].Message)
        }
    }
    if ($bad.Count -eq 0) { $true } else { "$($bad.Count) of $($blocks.Count): " + ($bad -join "; ") }
}

Check "the shipped audit prompts carry every clause" {
    # The defect this catches passed every other check in this file: the driver
    # PARSED, its 33 checks were green, and a clause written with embedded
    # double quotes had silently turned the rest of the prompt into a comment.
    # Only the artefact showed it, three hours into a run. Nothing here reads an
    # assembled prompt except this.
    $gate = Join-Path $Kit "bin\Test\verify-audit-prompt.ps1"
    $driver = Join-Path $Kit "bin\aider-plan.ps1"
    if (-not (Test-Path -LiteralPath $gate)) { return "the kit does not ship $gate" }
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $gate -Driver $driver 2>&1
    if ($LASTEXITCODE -eq 0) { $true } else { ($out | Select-Object -Last 4) -join "; " }
}

Check "no compiled Python anywhere in the kit" {
    $pyc = @(Get-ChildItem -LiteralPath $Kit -Recurse -File -Force |
             Where-Object { $_.Extension -eq ".pyc" -or $_.Directory.Name -eq "__pycache__" })
    if ($pyc.Count -eq 0) { $true } else { "$($pyc.Count) artefact(s), first: $($pyc[0].Name)" }
}

# --- 4. the install ---------------------------------------------------------
$scratch = Join-Path $env:TEMP ("gate-home-" + [guid]::NewGuid().ToString("N").Substring(0,8))
$fixture = ""

Write-Host ""
Write-Host "== Installing into $scratch =="

Check "setup.ps1 installs into a scratch home and exits 0" {
    $null = & (Join-Path $Kit "setup.ps1") -HomeDir $scratch -NoInstall *>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) { $true } else { "setup.ps1 exited $code" }
}

# --- 5. what the copy did to the bytes --------------------------------------
Check "no {{HOME}} placeholder survives in the installed tree" {
    # Regex, NOT -SimpleMatch with an escaped pattern: aider-night.ps1 carries the
    # literal text \{\{HOME\}\} inside its own guard, and a SimpleMatch on the
    # escaped form reports that guard as a leak. Measured 2026-09-04 - the first
    # version of this check produced exactly that false positive.
    $hit = @(Get-ChildItem -LiteralPath $scratch -Recurse -File |
             Select-String -Pattern '\{\{HOME\}\}' -List)
    if ($hit.Count -eq 0) { $true }
    else { "survived in: " + (($hit | ForEach-Object { $_.Path.Substring($scratch.Length + 1) }) -join ", ") }
}

Check "no installed file begins with a byte order mark" {
    # THE check this script was written for. PowerShell 5.1's Set-Content
    # -Encoding UTF8 writes EF BB BF, and aider's YAML parser refuses the config
    # it produces. The kit's copy is clean; only the installed one is not.
    $bom = @()
    foreach ($f in (Get-ChildItem -LiteralPath $scratch -Recurse -File)) {
        $b = [System.IO.File]::ReadAllBytes($f.FullName)
        if ($b.Count -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
            $bom += $f.FullName.Substring($scratch.Length + 1)
        }
    }
    if ($bom.Count -eq 0) { $true } else { "BOM in: " + ($bom -join ", ") }
}

# --- 6. does the installed thing actually start ------------------------------
Write-Host ""
Write-Host "== Starting the installed driver =="

Check "the driver RUN FROM THE INSTALLATION completes a dry run" {
    if (-not (Test-Path -LiteralPath $abHarness)) {
        return "aider-ab.ps1 is not at $abHarness, so no fixture can be built"
    }
    $script:fixtureLocal = Join-Path $env:TEMP ("gate-fx-" + [guid]::NewGuid().ToString("N").Substring(0,8))
    $null = & $abHarness fixture -Out $script:fixtureLocal *>&1
    if (-not (Test-Path -LiteralPath $script:fixtureLocal)) { return "the fixture was not created" }
    Push-Location $script:fixtureLocal
    try {
        $out = & (Join-Path $scratch ".local\bin\aider-plan.ps1") -DryRun `
                    -Config (Join-Path $scratch ".aider.conf.yml") `
                    -BudgetFile (Join-Path $scratch ".config\aider\context-budget.json") `
                    -TestCommand 'python -m unittest discover -s Test -p "test_*.py"' *>&1
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    $lines = @($out | ForEach-Object { $_.ToString() })
    if ($code -ne 0) {
        # The last lines carry the reason. aider's own refusals arrive at the END
        # of its usage text, so quoting the head would print argument syntax and
        # hide the message.
        return ("exit $code; last lines: " + (($lines | Select-Object -Last 3) -join " | "))
    }
    if (-not ($lines -join "`n" -match '(?m)^== Plan:')) { return "exit 0 but no plan was planned" }
    $true
}
$fixture = $script:fixtureLocal

# --- report and teardown ----------------------------------------------------
Write-Host ""
if ($Report -ne "") {
    $payload = [pscustomobject]@{
        taken         = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        kit           = $Kit
        scratch_home  = $scratch
        declaration   = ($Kit + ".declared")
        failures      = $script:failures
        checks        = $script:results
    }
    $json = $payload | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Report, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "report: $Report"
}

function Remove-Tree([string]$path) {
    # rmdir inside cmd, not [System.IO.Directory]::Delete. Measured 2026-09-04 on
    # this script's own first run: the fixture is a git repository, git marks the
    # files under .git\objects READ-ONLY, and .NET's Delete throws
    # UnauthorizedAccessException on the first one. `rmdir /s /q` removes them.
    if ($path -eq "" -or -not (Test-Path -LiteralPath $path)) { return }
    & cmd /c "rmdir /s /q `"$path`" 2>NUL"
    if (Test-Path -LiteralPath $path) {
        Write-Host ("  (could not delete {0} - remove it by hand)" -f $path) -ForegroundColor Yellow
    }
}

# The teardown can NEVER change the verdict. On that same first run the delete
# threw after every check had passed, the script died before printing its result,
# and $LASTEXITCODE carried 0 from an unrelated command - so a crashed gate
# reported success. A cleanup failure is a message, not an outcome.
try {
    if ($KeepScratch) {
        Write-Host "kept: $Kit"
        Write-Host "kept: $scratch"
        if ($fixture -ne "") { Write-Host "kept: $fixture" }
    } else {
        Remove-Tree $scratch
        Remove-Tree $fixture
        if ($builtHere) { Remove-Tree $Kit }
    }
} catch {
    Write-Host ("  (teardown failed: {0})" -f $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ""
if ($script:failures -eq 0) {
    Write-Host ("PASSED {0} checks. The kit installs and starts." -f $script:results.Count) -ForegroundColor Green
} else {
    Write-Host ("FAILED {0} of {1} checks. Do not publish." -f $script:failures, $script:results.Count) -ForegroundColor Red
}
exit $(if ($script:failures) { 1 } else { 0 })
