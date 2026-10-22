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
# The update-plan library is loaded when present, so that a missing library fails its own
# checks one by one instead of aborting the whole verifier.
$updateLibrary = Join-Path $RepoRoot "scripts\lib\rt-update.ps1"
if (Test-Path $updateLibrary) { . $updateLibrary }

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

    # --- update of a changed hook entry (-UpdateChanged) ---------------------
    # Measured 2026-10-17: the Stop reminder was rewritten in settings.template.json and
    # Merge-RtGlobalSettings could not deliver it, because it skips an entry as soon as its
    # token is found anywhere in the live file and never compares the command, so every
    # student had to edit settings.json by hand. The update is explicit (a switch), edits the
    # file as TEXT, keeps a backup, and refuses when it cannot be sure which entry is meant.
    Write-Host ""
    Write-Host "  -- update changed hook entries --" -ForegroundColor DarkCyan

    $updDir = Join-Path $Scratch "update"
    New-Item -ItemType Directory -Path $updDir -Force | Out-Null

    function Get-Prop($Object, [string]$Name) {
        if ($null -ne $Object -and $Object.PSObject.Properties.Name.Contains($Name)) { return $Object.$Name }
        return $null
    }
    function Invoke-Update([string]$Template, [string]$Live, [switch]$Switch, [switch]$Preview,
                           [string]$Stamp = "t1", [scriptblock]$ReadBack, [string[]]$Keep) {
        try {
            $splat = @{ TemplatePath = $Template; TargetPath = $Live; Vars = $settingsVars }
            if ($Keep)     { $splat.KeepHooks = $Keep }
            if ($Switch)   { $splat.UpdateChanged = $true; $splat.BackupStamp = $Stamp }
            if ($Preview)  { $splat.Preview = $true }
            if ($ReadBack) { $splat.ReadBack = $ReadBack }
            return (Merge-RtGlobalSettings @splat)
        } catch { return $null }
    }
    function Write-HookFile([string]$Path, [string]$Text) { Write-RtTextNoBom -Path $Path -Text $Text }
    function Get-Hash([string]$Path) { (Get-FileHash $Path -Algorithm SHA256).Hash }

    # JSON literals written by hand, so the fixtures do not depend on the code under test.
    $newCmdLit  = '"new <y> my-hook.py \"r\""'
    $oldCmdLit  = '"old <x> my-hook.py \"q\""'
    $oldCmdPs   = '"old <x> my-hook.py \"q\""'
    $oldCmdOdd  = '"old <x> my-hook.py \"q\" a\/b"'
    $newStatLit = '"new status"'
    $oldStatLit = '"old status"'

    function New-LiveText([string]$CmdLit, [string]$StatLit, [string]$Extra = "", [string]$AfterStop = "") {
        return @"
{
  "env": { "KEEP": "me" },
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": $CmdLit, "timeout": 99, "shell": "bash", "statusMessage": $StatLit } ] },
      { "hooks": [ { "type": "command", "command": "python other-tool.py" } ] }$Extra
    ]$AfterStop
  }
}
"@
    }
    $updTemplate = Join-Path $updDir "template.json"
    Write-HookFile $updTemplate @"
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": $newCmdLit, "timeout": 15, "shell": "bash", "statusMessage": $newStatLit } ] }
    ]
  }
}
"@

    # Without the switch: reported, never written.
    $liveA = Join-Path $updDir "a.json"
    $textA = New-LiveText $oldCmdLit $oldStatLit
    Write-HookFile $liveA $textA
    $hashA = Get-Hash $liveA
    $r = Invoke-Update $updTemplate $liveA
    Check "without the switch a changed entry is REPORTED in Differs" `
        ($null -ne $r -and @((Get-Prop $r "Differs")).Count -eq 1)
    Check "without the switch the file is byte-identical" ((Get-Hash $liveA) -eq $hashA)

    # -Preview with the switch: listed, not written, no backup.
    $r = Invoke-Update $updTemplate $liveA -Switch -Preview
    Check "-Preview with the switch lists the entry it would update" `
        ($null -ne $r -and @((Get-Prop $r "Updated")).Count -eq 1)
    Check "-Preview with the switch writes nothing and makes no backup (R16)" `
        ((Get-Hash $liveA) -eq $hashA -and @(Get-ChildItem "$liveA.bak-*" -ErrorAction SilentlyContinue).Count -eq 0)

    # The update itself.
    $r = Invoke-Update $updTemplate $liveA -Switch
    $after = [System.IO.File]::ReadAllText($liveA)
    $parsedAfter = $null
    try { $parsedAfter = $after | ConvertFrom-Json } catch { $parsedAfter = $null }
    Check "the update reports Updated" ($null -ne $r -and (Get-Prop $r "Action") -eq "updated")
    Check "the updated file parses" ($null -ne $parsedAfter)
    $hookAfter = if ($parsedAfter) { $parsedAfter.hooks.Stop[0].hooks[0] } else { $null }
    Check "the command now equals the template's" `
        ($null -ne $hookAfter -and $hookAfter.command -eq 'new <y> my-hook.py "r"')
    Check "the statusMessage now equals the template's" `
        ($null -ne $hookAfter -and $hookAfter.statusMessage -eq "new status")
    Check "the keys the update does not own (timeout, shell) are unchanged" `
        ($null -ne $hookAfter -and $hookAfter.timeout -eq 99 -and $hookAfter.shell -eq "bash")
    Check "reversing the two replaced literals restores the original text byte for byte" `
        ($after.Replace($newCmdLit, $oldCmdLit).Replace($newStatLit, $oldStatLit) -eq $textA)
    Check "an entry added by hand under another token is untouched" `
        ($after.Contains('"command": "python other-tool.py"') -and $after.Contains('"KEEP": "me"'))
    $backupsA = @(Get-ChildItem "$liveA.bak-*" -ErrorAction SilentlyContinue)
    Check "a timestamped backup holds the old text" `
        ($backupsA.Count -eq 1 -and [System.IO.File]::ReadAllText($backupsA[0].FullName) -eq $textA)
    Check "no BOM after the update" (-not (Test-HasBom $liveA))

    $r = Invoke-Update $updTemplate $liveA -Switch
    Check "a second update is a no-op" `
        ($null -ne $r -and (Get-Prop $r "Action") -eq "unchanged" -and @((Get-Prop $r "Differs")).Count -eq 0)

    # The old value written with PowerShell's own escaping is still located.
    $liveB = Join-Path $updDir "b.json"
    Write-HookFile $liveB (New-LiveText $oldCmdPs $oldStatLit)
    $r = Invoke-Update $updTemplate $liveB -Switch
    $afterB = [System.IO.File]::ReadAllText($liveB)
    Check "a command written with PowerShell escapes is located and updated" `
        ($null -ne $r -and (Get-Prop $r "Action") -eq "updated" -and -not $afterB.Contains("u003c") -and $afterB.Contains($newCmdLit))

    # Refusals: the file must stay byte-identical.
    $liveC = Join-Path $updDir "c.json"      # the old literal occurs twice, in two events
    $afterStopC = ",`r`n    `"Notification`": [ { `"hooks`": [ { `"type`": `"command`", `"command`": $oldCmdLit } ] } ]"
    Write-HookFile $liveC (New-LiveText $oldCmdLit $oldStatLit "" $afterStopC)
    $hashC = Get-Hash $liveC
    $r = Invoke-Update $updTemplate $liveC -Switch
    Check "an old literal that occurs twice is reported 'cannot locate' and the file is untouched" `
        ($null -ne $r -and (Get-Hash $liveC) -eq $hashC -and
         @((Get-Prop $r "Skipped") | Where-Object { $_.Reason -like "*cannot locate*" }).Count -ge 1)

    $liveD = Join-Path $updDir "d.json"      # a spelling neither form produces
    Write-HookFile $liveD (New-LiveText $oldCmdOdd $oldStatLit)
    $hashD = Get-Hash $liveD
    $r = Invoke-Update $updTemplate $liveD -Switch
    Check "an unknown escape spelling is reported 'cannot locate' and the file is untouched" `
        ($null -ne $r -and (Get-Hash $liveD) -eq $hashD -and
         @((Get-Prop $r "Skipped") | Where-Object { $_.Reason -like "*cannot locate*" }).Count -ge 1)

    $liveE = Join-Path $updDir "e.json"      # two live entries share the template's token
    $extraE = ",`r`n      { `"hooks`": [ { `"type`": `"command`", `"command`": `"run my-hook.py again`" } ] }"
    Write-HookFile $liveE (New-LiveText $oldCmdLit $oldStatLit $extraE)
    $hashE = Get-Hash $liveE
    $r = Invoke-Update $updTemplate $liveE -Switch
    Check "two live entries with the template's token are refused, naming the ambiguity" `
        ($null -ne $r -and (Get-Hash $liveE) -eq $hashE -and
         @((Get-Prop $r "Skipped") | Where-Object { $_.Reason -like "*more than one*" }).Count -ge 1)

    # A deliberate local variant is kept on request (-KeepHooks). Measured 2026-10-17: the owner's
    # [AUTO-SYNC CHECK] entry differs from the template only by the folder-name guard, on purpose,
    # and the update would have replaced it and silently stopped it running on that machine.
    $liveK = Join-Path $updDir "k.json"
    Write-HookFile $liveK (New-LiveText $oldCmdLit $oldStatLit)
    $hashK = Get-Hash $liveK
    $r = Invoke-Update $updTemplate $liveK -Switch -Keep @("my-hook.py")
    Check "a kept entry is not replaced and the file stays byte-identical" `
        ($null -ne $r -and (Get-Hash $liveK) -eq $hashK -and (Get-Prop $r "Action") -eq "unchanged")
    Check "a kept entry is listed in Kept, not in Updated or Differs" `
        ($null -ne $r -and @((Get-Prop $r "Kept")).Count -eq 1 -and @((Get-Prop $r "Updated")).Count -eq 0 -and @((Get-Prop $r "Differs")).Count -eq 0)
    Check "a kept entry makes no backup" (@(Get-ChildItem "$liveK.bak-*" -ErrorAction SilentlyContinue).Count -eq 0)
    $r = Invoke-Update $updTemplate $liveK -Switch -Keep @("MY-HOOK.PY")
    Check "the kept name is matched without regard to case" `
        ($null -ne $r -and (Get-Hash $liveK) -eq $hashK -and @((Get-Prop $r "Kept")).Count -eq 1)
    $r = Invoke-Update $updTemplate $liveK -Switch -Keep @("some-other-hook.py")
    Check "(control) an entry not named in -KeepHooks is still updated" `
        ($null -ne $r -and (Get-Prop $r "Action") -eq "updated" -and @((Get-Prop $r "Kept")).Count -eq 0)

    # A comma list reaches the script as ONE string when it is run with -File, and the manual says
    # several names are separated by commas (code-review finding, 2026-10-22).
    Write-HookFile $liveK (New-LiveText $oldCmdLit $oldStatLit)   # the control above updated it
    $hashK = Get-Hash $liveK
    $r = Invoke-Update $updTemplate $liveK -Switch -Keep @("some-other.py, my-hook.py")
    Check "a comma-separated list of kept names is split" `
        ($null -ne $r -and (Get-Hash $liveK) -eq $hashK -and @((Get-Prop $r "Kept")).Count -eq 1)
    $r = Invoke-Update $updTemplate $liveK -Switch -Keep @("some-other.py,third.py")
    Check "(control) a comma list naming no live entry keeps nothing and still updates" `
        ($null -ne $r -and (Get-Prop $r "Action") -eq "updated" -and @((Get-Prop $r "Kept")).Count -eq 0)

    # A live entry with the template's command but NO statusMessage can never be fixed by a text
    # replace. It must be said, not reported as "already present" (code-review finding).
    $liveS = Join-Path $updDir "s.json"
    Write-HookFile $liveS ('{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": ' + $newCmdLit + ' } ] } ] } }')
    $hashS = Get-Hash $liveS
    $r = Invoke-Update $updTemplate $liveS -Switch
    Check "a live entry without statusMessage is left untouched" ($null -ne $r -and (Get-Hash $liveS) -eq $hashS)
    Check "it is reported as skipped, naming the statusMessage" `
        ($null -ne $r -and @((Get-Prop $r "Skipped") | Where-Object { $_.Reason -like "*statusMessage*" }).Count -eq 1)
    Check "the message no longer claims every entry is already present" `
        ($null -ne $r -and (Get-Prop $r "Message") -notlike "*already present*")

    # The bracket tag of an inline hook is accepted with or without its brackets.
    $tagTemplate = Join-Path $updDir "template-tag.json"
    Write-HookFile $tagTemplate '{ "hooks": { "SessionStart": [ { "hooks": [ { "type": "command", "command": "echo \"[TAG ONE] new\"" } ] } ] } }'
    $liveT = Join-Path $updDir "t.json"
    Write-HookFile $liveT '{ "hooks": { "SessionStart": [ { "hooks": [ { "type": "command", "command": "echo \"[TAG ONE] mine\"" } ] } ] } }'
    $hashT = Get-Hash $liveT
    $r = Invoke-Update $tagTemplate $liveT -Switch -Keep @("TAG ONE")
    Check "an inline hook is kept by its tag without brackets" ($null -ne $r -and (Get-Hash $liveT) -eq $hashT -and @((Get-Prop $r "Kept")).Count -eq 1)
    $r = Invoke-Update $tagTemplate $liveT -Switch -Keep @("[TAG ONE]")
    Check "an inline hook is kept by its tag with brackets" ($null -ne $r -and (Get-Hash $liveT) -eq $hashT -and @((Get-Prop $r "Kept")).Count -eq 1)
    $r = Invoke-Update $tagTemplate $liveT -Switch
    Check "(control) the same inline hook is updated when not kept" ($null -ne $r -and (Get-Prop $r "Action") -eq "updated")

    # A template entry with no statusMessage leaves the live one alone.
    $templateNoStat = Join-Path $updDir "template-nostat.json"
    Write-HookFile $templateNoStat @"
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": $newCmdLit } ] } ] } }
"@
    $liveF = Join-Path $updDir "f.json"
    Write-HookFile $liveF (New-LiveText $oldCmdLit '"keep me"')
    $r = Invoke-Update $templateNoStat $liveF -Switch
    $afterF = [System.IO.File]::ReadAllText($liveF)
    Check "a template entry without statusMessage leaves the live statusMessage alone" `
        ($null -ne $r -and $afterF.Contains('"keep me"') -and $afterF.Contains($newCmdLit))

    # Two backups with the same stamp never collide.
    $liveG = Join-Path $updDir "g.json"
    Write-HookFile $liveG $textA
    Invoke-Update $updTemplate $liveG -Switch -Stamp "same" | Out-Null
    Write-HookFile $liveG $textA
    Invoke-Update $updTemplate $liveG -Switch -Stamp "same" | Out-Null
    Check "two updates with the same stamp make two distinct backups" `
        (@(Get-ChildItem "$liveG.bak-same*" -ErrorAction SilentlyContinue).Count -eq 2)

    # A read-back that does not parse restores the file (R9).
    $liveH = Join-Path $updDir "h.json"
    Write-HookFile $liveH $textA
    $hashH = Get-Hash $liveH
    $r = Invoke-Update $updTemplate $liveH -Switch -ReadBack { param($p) "{ broken" }
    Check "a read-back that does not parse restores the file and says so" `
        ($null -ne $r -and (Get-Prop $r "Action") -eq "restored" -and (Get-Hash $liveH) -eq $hashH)

    # --- the whole update in one command (-Update): the plan and its questions ---
    # Requested by the owner 2026-10-17: ask the profile, ask about Copilot, then run setup,
    # the links, the mirrors, the sync and the check, in that order. The order and flags are
    # data produced by pure functions, so they are proven here without running an installer.
    Write-Host ""
    Write-Host "  -- update plan --" -ForegroundColor DarkCyan

    function Invoke-Safe([scriptblock]$Block) { try { return (& $Block) } catch { return $null } }
    function Invoke-SafeList([scriptblock]$Block) { try { $r = & $Block; return ,@($r) } catch { return ,@() } }

    $profilesDir = Join-Path $Scratch "profiles"
    New-Item -ItemType Directory -Path $profilesDir -Force | Out-Null
    foreach ($n in "engineering", "cosmetic", "alpha") { Write-HookFile (Join-Path $profilesDir "$n.yaml") "name: $n" }
    Write-HookFile (Join-Path $profilesDir "README.md") "not a profile"
    $names = (Invoke-SafeList { Get-RtProfileNames -ProfilesDir $profilesDir })
    Check "the profile names are the .yaml files of the folder, sorted, and nothing else" `
        (($names -join ",") -eq "alpha,cosmetic,engineering")
    $claudeFixture = Join-Path $Scratch "claude-fixture.md"
    Write-HookFile $claudeFixture "intro`r`n`r`nactive_profile: cosmetic`r`n`r`nProfil actif : cosmetic`r`n"
    Check "the current profile is read from the active_profile line" `
        ((Invoke-Safe { Get-RtActiveProfile -ClaudeMdPath $claudeFixture }) -eq "cosmetic")
    Check "a missing file gives an empty current profile, not an error" `
        ($null -ne (Get-Command Get-RtActiveProfile -ErrorAction SilentlyContinue) -and
         [string](Invoke-Safe { Get-RtActiveProfile -ClaudeMdPath (Join-Path $Scratch "none.md") }) -eq "")

    $avail = @("alpha", "cosmetic", "engineering")
    Check "an empty answer chooses the current profile" `
        ((Invoke-Safe { Resolve-RtUpdateProfile -Answer "" -Available $avail -Current "cosmetic" }) -eq "cosmetic")
    Check "a known name is accepted, whatever its case" `
        ((Invoke-Safe { Resolve-RtUpdateProfile -Answer " ENGINEERING " -Available $avail -Current "cosmetic" }) -eq "engineering")
    Check "an unknown name is refused (null), never guessed" `
        ($null -eq (Invoke-Safe { Resolve-RtUpdateProfile -Answer "nope" -Available $avail -Current "cosmetic" }))
    Check "a name that is a path is refused" `
        ($null -eq (Invoke-Safe { Resolve-RtUpdateProfile -Answer "..\engineering" -Available $avail -Current "cosmetic" }))
    Check "an empty answer with no usable current profile is refused" `
        ($null -eq (Invoke-Safe { Resolve-RtUpdateProfile -Answer "" -Available $avail -Current "" }))

    $plan = (Invoke-SafeList { Resolve-RtUpdatePlan -Profile "engineering" -Personal $false -RunSuite $false -Preview $false })
    Check "the plan runs config, links, mirrors, sync and the check, in that order" `
        (($plan | ForEach-Object { $_.Id }) -join "," -eq "config,junctions,tools,sync,check")
    $planSuite = (Invoke-SafeList { Resolve-RtUpdatePlan -Profile "engineering" -Personal $false -RunSuite $true -Preview $false })
    Check "with the suite, it runs just before the sync" `
        (($planSuite | ForEach-Object { $_.Id }) -join "," -eq "config,junctions,tools,suite,sync,check")
    Check "the config step carries the hook update" `
        ($plan.Count -gt 0 -and (Get-Prop $plan[0] "UpdateHooks") -eq $true)
    $tools = $plan | Where-Object { $_.Id -eq "tools" }
    Check "the mirrors step carries the chosen profile and no Copilot by default" `
        ($null -ne $tools -and $tools.Profile -eq "engineering" -and $tools.Personal -eq $false)
    $planCopilot = (Invoke-SafeList { Resolve-RtUpdatePlan -Profile "cosmetic" -Personal $true -RunSuite $false -Preview $false })
    $toolsCopilot = $planCopilot | Where-Object { $_.Id -eq "tools" }
    Check "choosing Copilot reaches the mirrors step" `
        ($null -ne $toolsCopilot -and $toolsCopilot.Personal -eq $true -and $toolsCopilot.Profile -eq "cosmetic")
    Check "every step has a label" `
        ($plan.Count -gt 0 -and @($plan | Where-Object { [string]::IsNullOrWhiteSpace($_.Label) }).Count -eq 0)

    $planPreview = (Invoke-SafeList { Resolve-RtUpdatePlan -Profile "engineering" -Personal $true -RunSuite $true -Preview $true })
    Check "in preview the suite is not in the plan" `
        (@($planPreview | Where-Object { $_.Id -eq "suite" }).Count -eq 0 -and $planPreview.Count -gt 0)
    Check "in preview the links and the sync run as WhatIf" `
        (@($planPreview | Where-Object { $_.Id -in "junctions", "sync" -and $_.WhatIf -eq $true }).Count -eq 2)
    $toolsPreview = $planPreview | Where-Object { $_.Id -eq "tools" }
    Check "in preview the mirrors step is skipped with a stated reason" `
        ($null -ne $toolsPreview -and $toolsPreview.Skipped -eq $true -and $toolsPreview.Reason -like "*preview*")
    $checkPreview = $planPreview | Where-Object { $_.Id -eq "check" }
    Check "the read-only deployment check stays in the plan in preview" `
        ($null -ne $checkPreview -and $checkPreview.Skipped -eq $false)

    # --- the -Update switch in setup.ps1 (wiring, read as text) ---
    $setupUpdate = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "setup.ps1"))
    Check "setup.ps1 declares -Update, -Profile and -RunSuite" `
        ($setupUpdate -match '\[switch\]\$Update' -and $setupUpdate -match '\[string\]\$DomainProfile' -and $setupUpdate -match '\[switch\]\$RunSuite')
    Check "setup.ps1 loads the update-plan library" ($setupUpdate -match 'rt-update\.ps1')
    Check "setup.ps1 passes the profile to install.ps1" ($setupUpdate -match '-Profile\s+\$')
    Check "setup.ps1 runs the sync and the deployment check" `
        ($setupUpdate -match 'install-junctions\.ps1' -and $setupUpdate -match '-Sync' -and $setupUpdate -match 'check-deployment\.ps1')
    Check "-Update forces the hook update" ($setupUpdate -match '\$Update[^\r\n]*\$UpdateHooks|\$UpdateHooks[^\r\n]*\$Update')
    Check "setup.ps1 names -Update in its help" ($setupUpdate -match '\.\\setup\.ps1 -Update(?!Hooks)')

    # --- the switch in setup.ps1 (wiring, read as text: setup.ps1 is never executed here) ---
    $setupText = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "setup.ps1"))
    Check "setup.ps1 declares the -UpdateHooks switch" ($setupText -match '\[switch\]\$UpdateHooks')
    Check "setup.ps1 passes the switch and a backup stamp to the merge" `
        ($setupText -match '-UpdateChanged:\$UpdateHooks' -and $setupText -match '-BackupStamp')
    Check "setup.ps1 names the switch in its help and tells how to use -Preview with it" `
        ($setupText -match '-UpdateHooks -Preview')
    # The verdict of -Update. Measured 2026-10-17: the links step exited 1 on stale agent copies that
    # the sync, two steps later, replaces, and -Update concluded "failed" on a state it then fixed.
    # The final deployment check reads the end state, so in -Update it is the judge. In preview
    # nothing is fixed, so the check lists what the real run would do and does not fail the preview.
    Check "-Update runs the links step as advisory, to be judged by the final check" `
        ($setupText -match 'Invoke-JunctionsScript\s+-Advisory')
    Check "the links function can report a conflict without failing the run" `
        ($setupText -match '(?s)function Invoke-JunctionsScript\s*\{.{0,900}?param\(\[switch\]\$Advisory\).*?\$Advisory -and.*?return.*?Set-InstallerExit "install-junctions\.ps1"' -and $setupText -match 'judged by the final')
    Check "a failing deployment check does not fail a preview" `
        ($setupText -match '(?s)function Invoke-CheckScript.*?\$Preview.*?Set-InstallerExit "check-deployment')
    # Code-review findings of 2026-10-22. setup.ps1 cannot be dot-sourced (it would prompt and write
    # to ~/.claude), so these wiring checks read the text, as the ones above do.
    Check "a refused or restored settings.json merge is counted in the exit code" `
        ($setupText -match '@\("refused", "restored"\) -contains \$settingsResult\.Action\)\s*\{\s*(#[^\n]*\n\s*)*Set-InstallerExit')
    Check "a detected-path flag is set from the paths that really exist" `
        ($setupText -match '\$script:HookPathsDetected = \(Test-Path -LiteralPath \$gitBashPath\) -and \(Test-Path -LiteralPath \$nodePath\)')
    Check "the hook update is applied only when those paths exist" `
        ($setupText -match '\$updateHooksNow = \$UpdateHooks -and \$script:HookPathsDetected' -and $setupText -match '-UpdateChanged:\$updateHooksNow')
    Check "an update skipped for a missing path is an error, not a quiet pass" `
        ($setupText -match '(?s)if \(\$UpdateHooks -and -not \$script:HookPathsDetected\).*?Set-InstallerExit')
    Check "setup.ps1 declares -KeepHooks as a list of names" ($setupText -match '\[string\[\]\]\$KeepHooks')
    Check "setup.ps1 passes -KeepHooks to the merge and reports what was kept" `
        ($setupText -match '-KeepHooks\s+\$KeepHooks' -and $setupText -match '\$settingsResult\.Kept')
    Check "setup.ps1 names -KeepHooks in its help and in the differ warning" `
        (([regex]::Matches($setupText, '-KeepHooks')).Count -ge 4)

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
