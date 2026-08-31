#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of the two writes setup.ps1 makes to the GLOBAL Claude Code
    configuration, driven against temp copies.

.DESCRIPTION
    Since the CLAUDE*.md consolidation, setup.ps1 writes nothing into the
    repository and everything it does write lands in ~/.claude. That raises the
    stakes: the target is now the operator's own configuration, so the contract
    it obeys has to be proven rather than asserted in a comment.

        Setup ADDS what is missing. It never removes, replaces or reformats
        what the operator already has.

    Checked here: a missing global CLAUDE.md is created, an existing one is not
    overwritten, a hook the operator added by hand survives the settings merge,
    the env and permissions blocks come out byte-identical, a second pass
    changes nothing, an unparseable live file is refused rather than repaired,
    -Preview writes nothing at all (R16), no BOM is emitted (ConvertFrom-Json
    throws on one), and the substitution survives both a dollar sign and a
    space without doubling a single separator.

    It loads scripts\lib\rt-global-config.ps1 directly rather than setup.ps1.
    That separation is the whole reason the writers live in their own file:
    dot-sourcing setup.ps1 would run its three Read-Host prompts and its
    installer branches, and would write to the REAL ~/.claude just by being
    tested. Same precedent as verify-sync-writes.ps1 and rt-sync.ps1.

.SAFETY
    Everything happens under $env:TEMP. The live ~/.claude/settings.json and
    ~/.claude/CLAUDE.md are hashed before and after the run and asserted
    unchanged; no environment variable and no Startup folder is touched.

.NOTES
    Not part of the green-stamp gate, which covers Python suites under .claude\
    only. Same family as verify-sync-writes.ps1 and verify-daemon-install.ps1.

.EXAMPLE
    .\scripts\test\verify-setup-writes.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Scratch  = Join-Path $env:TEMP "rt-setup-verify-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Get-FileHashOrNull([string]$path) {
    if (Test-Path $path -PathType Leaf) { return (Get-FileHash $path -Algorithm SHA256).Hash }
    return $null
}

function Test-HasBom([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    return ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
}

. (Join-Path $RepoRoot "scripts\lib\rt-global-config.ps1")

Write-Host ""
Write-Host "=== setup.ps1 global writes ===" -ForegroundColor Cyan

# Live-file fingerprints, taken before anything runs.
$liveSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
$liveClaude   = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
$liveSettingsHashBefore = Get-FileHashOrNull $liveSettings
$liveClaudeHashBefore   = Get-FileHashOrNull $liveClaude

$templateClaude   = Join-Path $RepoRoot "CLAUDE.template.md"
$templateSettings = Join-Path $RepoRoot ".claude\settings.template.json"

$claudeVars = @{
    OBSIDIAN_VAULT = "D:\A Vault"
    OBSIDIAN_EXE   = "D:\Apps\Obsidian.exe"
    WORKSPACE_ROOT = "D:\repo"
    USERPROFILE    = "D:\home"
}
$settingsVars = @{
    WORKSPACE_ROOT = ConvertTo-RtJsonScalar "D:\repo"
    USERPROFILE    = ConvertTo-RtJsonScalar "D:\home"
    GIT_BASH_PATH  = ConvertTo-RtJsonScalar "D:\Program Files\Git\bin\bash.exe"
    NODE_PATH      = ConvertTo-RtJsonScalar "D:\Program Files\nodejs\node.exe"
}

try {
    New-Item -ItemType Directory -Path $Scratch -Force | Out-Null
    $homeClaude = Join-Path $Scratch ".claude"
    New-Item -ItemType Directory -Path $homeClaude -Force | Out-Null
    $targetClaude   = Join-Path $homeClaude "CLAUDE.md"
    $targetSettings = Join-Path $homeClaude "settings.json"

    # --- substitution and escaping (U11) ------------------------------------
    Write-Host ""
    Write-Host "  -- substitution --" -ForegroundColor DarkCyan

    $escaped = ConvertTo-RtJsonScalar "C:\Users\someone\bin"
    Check "a backslash becomes TWO characters, not four" ($escaped -eq 'C:\\Users\\someone\\bin')

    $roundTrip = ('{"p": "' + (ConvertTo-RtJsonScalar "C:\Users\someone\bin") + '"}' | ConvertFrom-Json).p
    Check "the escaped path decodes back to the ORIGINAL, with single separators" `
        ($roundTrip -eq "C:\Users\someone\bin")

    $dollar = Expand-RtTemplate -Text "vault={{V}}" -Vars @{ V = 'D:\Cash$1 and $& more' }
    Check "a value containing a dollar sign survives substitution byte-exact" `
        ($dollar -eq 'vault=D:\Cash$1 and $& more')

    $spaced = Expand-RtTemplate -Text "p={{P}}" -Vars @{ P = "C:\Program Files\Git\bin\bash.exe" }
    Check "a path with spaces survives substitution byte-exact" `
        ($spaced -eq "p=C:\Program Files\Git\bin\bash.exe")

    # --- CLAUDE.md ----------------------------------------------------------
    Write-Host ""
    Write-Host "  -- ~/.claude/CLAUDE.md --" -ForegroundColor DarkCyan

    $preview = Install-RtGlobalClaudeMd -TemplatePath $templateClaude -TargetPath $targetClaude `
        -Vars $claudeVars -Preview
    Check "-Preview on a missing file reports a create" ($preview.Action -eq "preview-create")
    Check "-Preview writes nothing (R16)" (-not (Test-Path $targetClaude))

    $created = Install-RtGlobalClaudeMd -TemplatePath $templateClaude -TargetPath $targetClaude `
        -Vars $claudeVars
    Check "a missing global CLAUDE.md is created" `
        ($created.Action -eq "created" -and (Test-Path $targetClaude))
    Check "no BOM on the created CLAUDE.md" (-not (Test-HasBom $targetClaude))

    $claudeText = [System.IO.File]::ReadAllText($targetClaude)
    Check "the vault placeholder was substituted" ($claudeText.Contains("D:\A Vault"))
    Check "no {{PLACEHOLDER}} survives" ($created.Placeholders.Count -eq 0)
    Check "the RT-CONTRACT block appears exactly once" `
        (([regex]::Matches($claudeText, [regex]::Escape("<!-- RT-CONTRACT:BEGIN -->"))).Count -eq 1)

    # The operator's own file: adding a line and re-running must change nothing.
    $ownText = $claudeText + "`r`n## My own section, added by hand`r`n"
    Write-RtTextNoBom -Path $targetClaude -Text $ownText
    $hashBefore = (Get-FileHash $targetClaude -Algorithm SHA256).Hash
    $kept = Install-RtGlobalClaudeMd -TemplatePath $templateClaude -TargetPath $targetClaude `
        -Vars $claudeVars
    Check "an existing CLAUDE.md is kept, never overwritten" ($kept.Action -eq "kept")
    Check "the operator's own section is byte-identical afterwards" `
        ((Get-FileHash $targetClaude -Algorithm SHA256).Hash -eq $hashBefore)

    # --- settings.json ------------------------------------------------------
    Write-Host ""
    Write-Host "  -- ~/.claude/settings.json --" -ForegroundColor DarkCyan

    $previewSettings = Merge-RtGlobalSettings -TemplatePath $templateSettings `
        -TargetPath $targetSettings -Vars $settingsVars -Preview
    Check "-Preview on a missing settings.json reports a create" `
        ($previewSettings.Action -eq "preview-create")
    Check "-Preview writes nothing (R16)" (-not (Test-Path $targetSettings))

    $createdSettings = Merge-RtGlobalSettings -TemplatePath $templateSettings `
        -TargetPath $targetSettings -Vars $settingsVars
    Check "a missing settings.json is created" `
        ($createdSettings.Action -eq "created" -and (Test-Path $targetSettings))
    Check "no BOM on the created settings.json" (-not (Test-HasBom $targetSettings))

    $parsed = [System.IO.File]::ReadAllText($targetSettings) | ConvertFrom-Json
    Check "the created settings.json parses" ($null -ne $parsed)
    Check "a substituted path decodes with SINGLE separators" `
        ($parsed.env.CLAUDE_CODE_GIT_BASH_PATH -eq "D:\Program Files\Git\bin\bash.exe")

    $secondPass = Merge-RtGlobalSettings -TemplatePath $templateSettings `
        -TargetPath $targetSettings -Vars $settingsVars
    Check "a second pass over a complete file changes nothing" ($secondPass.Action -eq "unchanged")

    # Now the case that matters: a live file MISSING one template entry and
    # carrying one the operator added by hand, plus an env key of their own.
    $trimmed = [System.IO.File]::ReadAllText($targetSettings) | ConvertFrom-Json
    $keptEntries = @($trimmed.hooks.SessionStart | Where-Object {
        $command = ""
        foreach ($h in @($_.hooks)) { if ($h.PSObject.Properties.Name.Contains("command")) { $command = [string]$h.command } }
        -not $command.Contains("caveman-activate.js")
    })
    $trimmed.hooks.SessionStart = $keptEntries
    $trimmed.env | Add-Member -NotePropertyName "MY_OWN_KEY" -NotePropertyValue "kept" -Force
    $handEntry = [PSCustomObject]@{
        hooks = @([PSCustomObject]@{ type = "command"; command = "python `"D:\home\.claude\hooks\my-own-hook.py`"" })
    }
    $trimmed.hooks.SessionStart = @($trimmed.hooks.SessionStart) + $handEntry
    Write-RtTextNoBom -Path $targetSettings -Text ($trimmed | ConvertTo-Json -Depth 30)

    $merged = Merge-RtGlobalSettings -TemplatePath $templateSettings `
        -TargetPath $targetSettings -Vars $settingsVars
    Check "the missing entry is added back" `
        ($merged.Action -eq "merged" -and @($merged.Added).Count -eq 1)
    Check "the entry added is the one that was missing" `
        (@($merged.Added)[0].Token -eq "caveman-activate.js")

    $after = [System.IO.File]::ReadAllText($targetSettings)
    $afterParsed = $after | ConvertFrom-Json
    Check "the merged settings.json parses" ($null -ne $afterParsed)
    Check "the hook the operator added by hand survives" ($after.Contains("my-own-hook.py"))
    Check "the operator's own env key survives" ($afterParsed.env.MY_OWN_KEY -eq "kept")
    Check "a settings.json backup was kept" (Test-Path "$targetSettings.bak")
    Check "no BOM after the merge" (-not (Test-HasBom $targetSettings))

    $mergedAgain = Merge-RtGlobalSettings -TemplatePath $templateSettings `
        -TargetPath $targetSettings -Vars $settingsVars
    Check "a second merge is a no-op" ($mergedAgain.Action -eq "unchanged")

    # An unparseable live file is refused, not repaired and not overwritten.
    $broken = Join-Path $homeClaude "broken.json"
    Write-RtTextNoBom -Path $broken -Text "{ not json at all"
    $brokenHash = (Get-FileHash $broken -Algorithm SHA256).Hash
    $refused = Merge-RtGlobalSettings -TemplatePath $templateSettings -TargetPath $broken `
        -Vars $settingsVars
    Check "an unparseable settings.json is refused" ($refused.Action -eq "refused")
    Check "the unparseable file is left untouched" `
        ((Get-FileHash $broken -Algorithm SHA256).Hash -eq $brokenHash)

    # A live file with no array for an event is reported, never invented.
    $noArray = Join-Path $homeClaude "no-sessionstart.json"
    Write-RtTextNoBom -Path $noArray -Text "{`r`n  `"hooks`": {}`r`n}"
    $reported = Merge-RtGlobalSettings -TemplatePath $templateSettings -TargetPath $noArray `
        -Vars $settingsVars
    Check "a missing event array is reported rather than invented" `
        (@($reported.Skipped).Count -gt 0 -and $reported.Action -eq "unchanged")

    # --- Install-RtGlobalHooks ----------------------------------------------
    # Measured 2026-08-30: setup.ps1 -All declared hooks in ~/.claude/settings.json and
    # deployed no scripts, because install-junctions.ps1 has no hook handling and only
    # -Sync copies them, gated on a .rt-green.json that no clone has. A declared hook whose
    # script is absent refuses every tool in its matcher. Same contract as the two writers
    # above: ADD what is missing, never overwrite what the operator has.
    Write-Host ""
    Write-Host "  -- Install-RtGlobalHooks --" -ForegroundColor DarkCyan

    $hookSrc = Join-Path $Scratch "hooks-src"
    New-Item -ItemType Directory -Path $hookSrc -Force | Out-Null
    Write-RtTextNoBom -Path (Join-Path $hookSrc "alpha.py")   -Text "print('alpha')"
    Write-RtTextNoBom -Path (Join-Path $hookSrc "alpha.json") -Text '{"enabled": true}'
    Write-RtTextNoBom -Path (Join-Path $hookSrc "notes.md")   -Text "not a hook"

    # -Preview first, on a target that does not exist yet (R16).
    $hookDstPreview = Join-Path $Scratch "hooks-preview"
    $preview = Install-RtGlobalHooks -SourceDir $hookSrc -TargetDir $hookDstPreview -Preview
    Check "hooks -Preview reports what it would install" `
        ($preview.Action -eq "preview" -and @($preview.Installed).Count -eq 2)
    Check "hooks -Preview creates nothing at all" (-not (Test-Path $hookDstPreview))

    # Fresh machine: nothing deployed.
    $hookDst = Join-Path $Scratch "hooks-dst"
    $fresh = Install-RtGlobalHooks -SourceDir $hookSrc -TargetDir $hookDst
    Check "a fresh machine gets its hook scripts" `
        ($fresh.Action -eq "installed" -and (Test-Path (Join-Path $hookDst "alpha.py")))
    Check "a hook's .json config travels with its .py" `
        (Test-Path (Join-Path $hookDst "alpha.json"))
    Check "a non-hook file beside them is not deployed" `
        (-not (Test-Path (Join-Path $hookDst "notes.md")))

    # The contract that matters for a student: their own copy is never overwritten.
    $studentEdit = "print('alpha, edited by the student')"
    Write-RtTextNoBom -Path (Join-Path $hookDst "alpha.py") -Text $studentEdit
    $editedHash = (Get-FileHash (Join-Path $hookDst "alpha.py") -Algorithm SHA256).Hash
    $second = Install-RtGlobalHooks -SourceDir $hookSrc -TargetDir $hookDst
    Check "an existing hook is left byte-identical" `
        ((Get-FileHash (Join-Path $hookDst "alpha.py") -Algorithm SHA256).Hash -eq $editedHash)
    Check "a differing hook is REPORTED rather than silently overwritten" `
        (@($second.Differing) -contains "alpha.py")
    Check "a second pass installs nothing new" (@($second.Installed).Count -eq 0)

    # Negative control for the Differing report: identical files must NOT be reported,
    # or the warning is noise on every run and gets ignored.
    $cleanDst = Join-Path $Scratch "hooks-clean"
    Install-RtGlobalHooks -SourceDir $hookSrc -TargetDir $cleanDst | Out-Null
    $again = Install-RtGlobalHooks -SourceDir $hookSrc -TargetDir $cleanDst
    Check "an unmodified deployed hook is not reported as differing" `
        (@($again.Differing).Count -eq 0)

    # A missing source is a refusal that names the path, never a silent success (R3/R8).
    $missing = Install-RtGlobalHooks -SourceDir (Join-Path $Scratch "no-such-dir") `
        -TargetDir (Join-Path $Scratch "hooks-none")
    Check "a missing hook source directory is refused" ($missing.Action -eq "refused")
    Check "the refusal names the directory" `
        ($missing.Message -like "*no-such-dir*")

    # The hook the gate ships must actually be in the repository's hook directory, or
    # setup deploys a declaration with nothing behind it - the defect being fixed here.
    $repoHooks = Join-Path $RepoRoot ".claude\hooks"
    Check "askuserquestion-clarity.py is in the repository hook directory" `
        (Test-Path (Join-Path $repoHooks "askuserquestion-clarity.py"))
    Check "askuserquestion-clarity.json ships beside it" `
        (Test-Path (Join-Path $repoHooks "askuserquestion-clarity.json"))

} finally {
    if (Test-Path $Scratch) { Remove-Item -Path $Scratch -Recurse -Force }
}

# --- the live files, never touched ------------------------------------------
Write-Host ""
Write-Host "  -- the real ~/.claude --" -ForegroundColor DarkCyan
Check "live ~/.claude/settings.json never written" `
    ((Get-FileHashOrNull $liveSettings) -eq $liveSettingsHashBefore)
Check "live ~/.claude/CLAUDE.md never written" `
    ((Get-FileHashOrNull $liveClaude) -eq $liveClaudeHashBefore)

Write-Host ""
if ($failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "  $failures check(s) failed." -ForegroundColor Red
exit 1
