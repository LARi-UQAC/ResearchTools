<#
    rt-global-config.ps1 - the two writers that fill the gaps in the GLOBAL
    Claude Code configuration, and nothing else.

    Loaded by setup.ps1. It lives in its own file for the same reason
    rt-sync.ps1 and rt-daemon-install.ps1 do: scripts/test/verify-setup-writes.ps1
    must be able to drive these functions against temp copies WITHOUT executing
    setup.ps1's interactive flow, which prompts three times and would otherwise
    write to the real ~/.claude just by being tested.

    THE CONTRACT, which every function here obeys:

        Setup ADDS what is missing. It never removes, replaces or reformats
        what the operator already has in a global file.

    That is why ~/.claude/CLAUDE.md is written only when it does not exist -
    a fresh machine has no global instructions and this is the only step that
    can supply them - and why an existing one is left alone entirely, with the
    RT-CONTRACT block maintained by install-junctions.ps1 -Sync instead.

    And why settings.json is merged by TEXT INSERTION rather than by
    reserialising the parsed document: ConvertTo-Json would rewrite the whole
    file's formatting, so every entry the operator added by hand and the entire
    env block stay byte-for-byte identical only if the document is never
    rebuilt. Parsed before and after; a result that does not parse is restored
    from the backup rather than shipped (R9 - verify the effect, not the
    return code).

    No BOM anywhere. Windows PowerShell's Set-Content -Encoding UTF8 prepends
    one, which is harmless in Markdown and fatal in JSON: ConvertFrom-Json
    throws on a leading U+FEFF. Both writers go through UTF8Encoding($false).
#>

# Which hook files are copied is rt-stamp.ps1's single definition, shared with -Sync and the
# green stamp, so the first-install path cannot drift from the update path (2026-10-16).
. (Join-Path $PSScriptRoot "rt-stamp.ps1")

Set-StrictMode -Version Latest

# --- primitives -------------------------------------------------------------

function Write-RtTextNoBom {
    <#
        The only write path in this file. UTF8Encoding($false) is the no-BOM
        constructor; see the header for why that is not a preference.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $encoding = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function ConvertTo-RtJsonScalar {
    <#
        Escape a value for embedding inside a JSON string literal: a backslash
        becomes TWO characters, not four.

        The four-character version is the defect this replaces. `-replace
        '\\', '\\\\'` looks like an escape of an escape, but the -replace
        REPLACEMENT string has its own backslash rules, so each backslash came
        out as two in the JSON source and therefore as two in the decoded
        value: C:\\Users\\... with doubled separators. Windows opens such a
        path anyway, which is why it survived unnoticed while the same file's
        other segments decoded correctly - one file, two spellings.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Expand-RtTemplate {
    <#
        Substitute {{KEY}} placeholders.

        .Replace(), never -replace: in a -replace REPLACEMENT string the dollar
        sign is a metacharacter ($1, $&, $$), so a path or a vault name
        containing one was silently corrupted. .Replace is literal on both
        sides and has no metacharacters at all.
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][hashtable]$Vars
    )
    $result = $Text
    foreach ($key in $Vars.Keys) {
        $result = $result.Replace("{{$key}}", [string]$Vars[$key])
    }
    return $result
}

function Get-RtUnreplacedPlaceholders {
    <#
        Every {{KEY}} the substitution did not fill, as a distinct list.

        The leading comma is not decoration: PowerShell unrolls a returned
        array, so an EMPTY one comes back as $null and the caller's
        .Count throws under Set-StrictMode. The nothing-left-to-replace case is
        the common one, so that would fail exactly when the run succeeded.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $found = [regex]::Matches($Text, '\{\{[A-Z_]+\}\}')
    return ,@($found | ForEach-Object { $_.Value } | Sort-Object -Unique)
}

function Get-RtHookToken {
    <#
        A short string that identifies one hook entry inside the live file's
        raw text, so "is this entry already there" is answered without
        reserialising anything.

        The script's own file name where there is one; otherwise the bracket
        tag an inline hook prints ([AUTO-SYNC CHECK], [RTK ACTIVE], ...), which
        is what makes the four inline entries distinguishable at all; otherwise
        the whole command, which is always correct and merely long.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Command)
    $script = [regex]::Match($Command, '[\w.\-]+\.(py|ps1|js|mjs|cjs)')
    if ($script.Success) { return $script.Value }
    $tag = [regex]::Match($Command, '\[[A-Z][A-Z \-]{2,}\]')
    if ($tag.Success) { return $tag.Value }
    return $Command
}

# --- ~/.claude/CLAUDE.md ----------------------------------------------------

function Install-RtGlobalClaudeMd {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Supply the global instructions on a machine that has none. An
            existing file is never touched: -Sync maintains its RT-CONTRACT
            block, and everything outside those markers belongs to the operator.

        Inputs:
            TemplatePath (string): CLAUDE.template.md
            TargetPath (string): destination, normally ~/.claude/CLAUDE.md
            Vars (hashtable): substitution values, NOT JSON-escaped (Markdown)
            Preview (switch): decide and report, write nothing

        Outputs:
            result (PSCustomObject): Action, Path, Message, Placeholders
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][hashtable]$Vars,
        [switch]$Preview
    )

    if (-not (Test-Path $TemplatePath -PathType Leaf)) {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Placeholders = @()
            Message = "template not found: $TemplatePath"
        }
    }

    if (Test-Path $TargetPath -PathType Leaf) {
        return [PSCustomObject]@{
            Action = "kept"; Path = $TargetPath; Placeholders = @()
            Message = "already exists, left untouched; install-junctions.ps1 -Sync maintains its RT-CONTRACT block"
        }
    }

    $content = Expand-RtTemplate -Text ([System.IO.File]::ReadAllText($TemplatePath)) -Vars $Vars
    $remaining = Get-RtUnreplacedPlaceholders -Text $content

    if ($Preview) {
        return [PSCustomObject]@{
            Action = "preview-create"; Path = $TargetPath; Placeholders = $remaining
            Message = "would create (absent today)"
        }
    }

    $parent = Split-Path $TargetPath -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Write-RtTextNoBom -Path $TargetPath -Text $content

    # R9: read back the state that was supposed to change, rather than trusting
    # that the write returned without throwing.
    if (-not (Test-Path $TargetPath -PathType Leaf)) {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Placeholders = $remaining
            Message = "write reported success but the file is absent"
        }
    }
    return [PSCustomObject]@{
        Action = "created"; Path = $TargetPath; Placeholders = $remaining
        Message = "created from CLAUDE.template.md"
    }
}

# --- ~/.claude/settings.json ------------------------------------------------

function Get-RtTemplateHookEntries {
    <#
        Flatten the template into one record per hook entry: the event it
        belongs to, its identifying token, and the entry object itself.
    #>
    param([Parameter(Mandatory = $true)]$Settings)

    # Leading commas throughout: an empty array returned from a function unrolls
    # to $null, and "the template declares no hooks" must stay a list.
    $entries = @()
    if (-not $Settings.PSObject.Properties.Name.Contains("hooks")) { return ,$entries }
    foreach ($eventProperty in $Settings.hooks.PSObject.Properties) {
        foreach ($entry in @($eventProperty.Value)) {
            $token = $null
            foreach ($hook in @($entry.hooks)) {
                if ($hook.PSObject.Properties.Name.Contains("command")) {
                    $token = Get-RtHookToken -Command ([string]$hook.command)
                    break
                }
            }
            if (-not $token) { continue }
            $entries += [PSCustomObject]@{
                Event = $eventProperty.Name
                Token = $token
                Entry = $entry
            }
        }
    }
    return ,$entries
}

function Get-RtJsonStringLiteral {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Spell a string as a quoted JSON literal, in one of the two ways a
            settings.json is found in the wild, so an old value can be located in
            the raw text and a new one written without reserialising the file.

        Inputs:
            Value (string): the decoded text
            Style (string): "minimal" escapes only the backslash, the double quote
                and control characters (what Claude Code and JSON.stringify write);
                "powershell" is ConvertTo-Json's own spelling, which also escapes
                < > & and the apostrophe as \uXXXX

        Outputs:
            literal (string): the value between double quotes, escaped
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [ValidateSet("minimal", "powershell")][string]$Style = "minimal"
    )
    if ($Style -eq "powershell") { return ($Value | ConvertTo-Json -Compress) }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    foreach ($ch in $Value.ToCharArray()) {
        $code = [int]$ch
        if     ($ch -ceq [char]34) { [void]$builder.Append('\"') }
        elseif ($ch -ceq [char]92) { [void]$builder.Append('\\') }
        elseif ($code -eq 8)       { [void]$builder.Append('\b') }
        elseif ($code -eq 9)       { [void]$builder.Append('\t') }
        elseif ($code -eq 10)      { [void]$builder.Append('\n') }
        elseif ($code -eq 12)      { [void]$builder.Append('\f') }
        elseif ($code -eq 13)      { [void]$builder.Append('\r') }
        elseif ($code -lt 32)      { [void]$builder.Append(('\u{0:x4}' -f $code)) }
        else                       { [void]$builder.Append($ch) }
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Get-RtLiteralLocation {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Find where a decoded value sits in the raw text of a JSON file, in
            either spelling of Get-RtJsonStringLiteral, and say whether it can be
            replaced with certainty.

        Inputs:
            Text (string): the raw JSON text
            Value (string): the decoded value to find

        Outputs:
            location (PSCustomObject): Count (total occurrences over both
            spellings) and Literal (the spelling found, only when Count is 1)
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    $candidates = @(Get-RtJsonStringLiteral -Value $Value -Style minimal)
    $powershellSpelling = Get-RtJsonStringLiteral -Value $Value -Style powershell
    if ($powershellSpelling -ne $candidates[0]) { $candidates += $powershellSpelling }
    $total = 0
    $found = $null
    foreach ($candidate in $candidates) {
        $at = 0
        while (($at = $Text.IndexOf($candidate, $at, [System.StringComparison]::Ordinal)) -ge 0) {
            $total++
            $found = $candidate
            $at += $candidate.Length
        }
    }
    return [PSCustomObject]@{ Count = $total; Literal = $(if ($total -eq 1) { $found } else { $null }) }
}

function Test-RtHookKept {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Tell whether a hook entry's token is named in the keep list. Case is
            ignored and the brackets of an inline tag are optional, so the list
            can be typed as the setup output prints it or without the brackets.

        Inputs:
            Token (string): from Get-RtHookToken
            Keep (string[]): names given to -KeepHooks, may be $null or empty

        Outputs:
            kept (bool): $true when the entry must be left as it is
        --------------------------------------------------------------------------
    #>
    param([string]$Token, [string[]]$Keep)
    if (-not $Keep) { return $false }
    $bare = $Token.Trim('[', ']')
    # A comma list typed after -File reaches the script as ONE string, so each item is split.
    foreach ($item in $Keep) {
        foreach ($name in ([string]$item -split ',')) {
            if ([string]::IsNullOrWhiteSpace($name)) { continue }
            if ([string]::Equals($name.Trim().Trim('[', ']'), $bare, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
        }
    }
    return $false
}

function Merge-RtGlobalSettings {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Add the hook entries the template declares and the live global
            settings lack, and, only when UpdateChanged is given, replace the
            command and statusMessage of a recognised live entry whose text
            differs from the template. Nothing else: no entry is removed, the env
            block and the permissions block are never rewritten, and the document
            is never reserialised.

        Inputs:
            TemplatePath, TargetPath, Vars, Preview: as Invoke-RtSettingsMerge
            UpdateChanged (switch): also update changed entries (a text edit)
            KeepHooks (string[]): tokens of entries to leave as they are (a deliberate
            local variant), matched without case and with or without brackets
            BackupStamp (string): suffix of the backup made before an update
            ReadBack (scriptblock): reads the file after the write, a test seam

        Outputs:
            result (PSCustomObject): Action, Path, Added, Skipped, Message, and
            always Updated, Differs and Kept (lists of records with Event and Token)
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][hashtable]$Vars,
        [switch]$Preview,
        [switch]$UpdateChanged,
        [string]$BackupStamp = "update",
        [scriptblock]$ReadBack,
        [string[]]$KeepHooks
    )
    $result = Invoke-RtSettingsMerge @PSBoundParameters
    foreach ($name in @("Updated", "Differs", "Kept")) {
        if (-not $result.PSObject.Properties.Name.Contains($name)) {
            $result | Add-Member -NotePropertyName $name -NotePropertyValue @()
        }
    }
    return $result
}

function Invoke-RtSettingsMerge {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Add the hook entries the template declares and the live global
            settings lack. Nothing else: no entry is removed, the env block and
            the permissions block are never rewritten, and the document is
            never reserialised.

        Inputs:
            TemplatePath (string): .claude/settings.template.json
            TargetPath (string): destination, normally ~/.claude/settings.json
            Vars (hashtable): substitution values, JSON-escaped by the caller
            Preview (switch): decide and report, write nothing

        Outputs:
            result (PSCustomObject): Action, Path, Added, Skipped, Message
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][hashtable]$Vars,
        [switch]$Preview,
        [switch]$UpdateChanged,
        [string]$BackupStamp = "update",
        [scriptblock]$ReadBack = { param($Path) [System.IO.File]::ReadAllText($Path) },
        [string[]]$KeepHooks
    )

    $empty = @()
    if (-not (Test-Path $TemplatePath -PathType Leaf)) {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Added = $empty; Skipped = $empty
            Message = "template not found: $TemplatePath"
        }
    }

    $templateText = Expand-RtTemplate -Text ([System.IO.File]::ReadAllText($TemplatePath)) -Vars $Vars
    try {
        $template = $templateText | ConvertFrom-Json
    } catch {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Added = $empty; Skipped = $empty
            Message = "the substituted template does not parse as JSON; nothing written"
        }
    }

    # Fresh machine: no global settings at all. Write the template whole, which
    # adds everything and removes nothing, since there is nothing to remove.
    if (-not (Test-Path $TargetPath -PathType Leaf)) {
        if ($Preview) {
            return [PSCustomObject]@{
                Action = "preview-create"; Path = $TargetPath; Added = $empty; Skipped = $empty
                Message = "would create from the template (absent today)"
            }
        }
        $parent = Split-Path $TargetPath -Parent
        if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Write-RtTextNoBom -Path $TargetPath -Text $templateText
        return [PSCustomObject]@{
            Action = "created"; Path = $TargetPath; Added = $empty; Skipped = $empty
            Message = "created from settings.template.json"
        }
    }

    $liveText = [System.IO.File]::ReadAllText($TargetPath)
    try {
        $null = $liveText | ConvertFrom-Json
    } catch {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Added = $empty; Skipped = $empty
            Message = "~/.claude/settings.json does not parse - not touching it"
        }
    }

    $added = @()
    $skipped = @()
    $merged = $liveText

    foreach ($record in (Get-RtTemplateHookEntries -Settings $template)) {
        if ($merged.Contains($record.Token)) { continue }

        # Whitespace-tolerant, because the file was not necessarily written by
        # the same tool twice: Claude Code writes `"SessionStart": [` and
        # PowerShell's own ConvertTo-Json writes `"SessionStart":  [` with two
        # spaces. A literal anchor matches one spelling and silently adds
        # nothing to the other, which reads exactly like "already present".
        $anchor = [regex]::Match($merged, '"' + [regex]::Escape($record.Event) + '"\s*:\s*\[')
        if (-not $anchor.Success) {
            # Creating a whole event array would mean deciding where it goes in
            # someone else's file. Report and leave it to them.
            $skipped += [PSCustomObject]@{
                Event = $record.Event; Token = $record.Token
                Reason = "no `"$($record.Event)`" array in the live file"
            }
            continue
        }

        $json = ($record.Entry | ConvertTo-Json -Depth 20 -Compress)
        $insertAt = $anchor.Index + $anchor.Length
        $merged = $merged.Substring(0, $insertAt) + "`r`n      " + $json + "," +
                  $merged.Substring($insertAt)
        $added += [PSCustomObject]@{ Event = $record.Event; Token = $record.Token }
    }

    # --- entries already present whose text differs from the template ---------
    # The add loop above skips an entry as soon as its token is anywhere in the file, so
    # a changed command was never delivered (measured 2026-10-17). Here the live entry is
    # found by its OWN token inside the same event, compared, and, only on request,
    # replaced as text. Anything uncertain is reported and left alone.
    $updated = @()
    $differs = @()
    $kept = @()
    $newLiterals = @()
    $liveObject = $liveText | ConvertFrom-Json
    foreach ($record in (Get-RtTemplateHookEntries -Settings $template)) {
        $templateHook = $null
        foreach ($candidateHook in @($record.Entry.hooks)) {
            if (($null -ne $candidateHook.PSObject.Properties["command"])) { $templateHook = $candidateHook; break }
        }
        if ($null -eq $templateHook) { continue }
        $wantStatus = ($null -ne $templateHook.PSObject.Properties["statusMessage"])

        $liveHooks = @()
        if (($null -ne $liveObject.PSObject.Properties["hooks"]) -and
            ($null -ne $liveObject.hooks.PSObject.Properties[$record.Event])) {
            foreach ($liveEntry in @($liveObject.hooks.($record.Event))) {
                foreach ($liveHookCandidate in @($liveEntry.hooks)) {
                    if (($null -ne $liveHookCandidate.PSObject.Properties["command"]) -and
                        (Get-RtHookToken -Command ([string]$liveHookCandidate.command)) -eq $record.Token) {
                        $liveHooks += $liveHookCandidate
                    }
                }
            }
        }
        if ($liveHooks.Count -eq 0) { continue }

        $current = @($liveHooks | Where-Object {
            [string]$_.command -ceq [string]$templateHook.command -and
            (-not $wantStatus -or
             (($null -ne $_.PSObject.Properties["statusMessage"]) -and
              [string]$_.statusMessage -ceq [string]$templateHook.statusMessage))
        })
        if ($current.Count -gt 0) { continue }

        if (Test-RtHookKept -Token $record.Token -Keep $KeepHooks) {
            $kept += [PSCustomObject]@{ Event = $record.Event; Token = $record.Token }
            continue
        }
        $differs += [PSCustomObject]@{ Event = $record.Event; Token = $record.Token }
        if ($liveHooks.Count -gt 1) {
            $skipped += [PSCustomObject]@{
                Event = $record.Event; Token = $record.Token
                Reason = "more than one live hook in $($record.Event) carries $($record.Token); not guessing which to update"
            }
            continue
        }
        if (-not $UpdateChanged) { continue }

        $liveHook = $liveHooks[0]
        $replacements = @()
        $unlocated = $null
        if ([string]$liveHook.command -cne [string]$templateHook.command) {
            $where = Get-RtLiteralLocation -Text $merged -Value ([string]$liveHook.command)
            if ($where.Count -ne 1) { $unlocated = "command (found $($where.Count) times)" }
            else { $replacements += [PSCustomObject]@{ Old = $where.Literal; New = (Get-RtJsonStringLiteral -Value ([string]$templateHook.command)) } }
        }
        if ($wantStatus -and ($null -ne $liveHook.PSObject.Properties["statusMessage"]) -and
            [string]$liveHook.statusMessage -cne [string]$templateHook.statusMessage) {
            $where = Get-RtLiteralLocation -Text $merged -Value ([string]$liveHook.statusMessage)
            if ($where.Count -ne 1) { $unlocated = "statusMessage (found $($where.Count) times)" }
            else { $replacements += [PSCustomObject]@{ Old = $where.Literal; New = (Get-RtJsonStringLiteral -Value ([string]$templateHook.statusMessage)) } }
        }
        if ($null -ne $unlocated) {
            $skipped += [PSCustomObject]@{
                Event = $record.Event; Token = $record.Token
                Reason = "cannot locate the old $unlocated exactly once in the live file; edit this entry by hand"
            }
            continue
        }
        if ($replacements.Count -eq 0) {
            # The command matches but the live entry has no statusMessage: a text replace cannot
            # insert a key with certainty, so say so instead of reading as "already present".
            if ($wantStatus -and ($null -eq $liveHook.PSObject.Properties["statusMessage"])) {
                $skipped += [PSCustomObject]@{
                    Event = $record.Event; Token = $record.Token
                    Reason = "the live entry has no statusMessage and a text edit cannot add one with certainty; add it by hand"
                }
            }
            continue
        }
        foreach ($replacement in $replacements) {
            $at = $merged.IndexOf($replacement.Old, [System.StringComparison]::Ordinal)
            $merged = $merged.Substring(0, $at) + $replacement.New + $merged.Substring($at + $replacement.Old.Length)
            $newLiterals += $replacement.New
        }
        $updated += [PSCustomObject]@{ Event = $record.Event; Token = $record.Token }
    }

    if ($added.Count -eq 0 -and $updated.Count -eq 0) {
        $note = if ($differs.Count -gt 0 -and -not $UpdateChanged) {
            "$($differs.Count) hook entr(y/ies) differ from the template; run setup.ps1 -UpdateHooks to update them"
        } elseif ($differs.Count -gt 0) {
            "$($differs.Count) hook entr(y/ies) differ from the template and could not be updated; see the entries reported as not updated"
        } else { "every hook entry the template declares is already present" }
        return [PSCustomObject]@{
            Action = "unchanged"; Path = $TargetPath; Added = $empty; Skipped = $skipped
            Updated = $empty; Differs = $differs; Kept = $kept; Message = $note
        }
    }

    if ($Preview) {
        return [PSCustomObject]@{
            Action = "preview-merge"; Path = $TargetPath; Added = $added; Skipped = $skipped
            Updated = $updated; Differs = $differs; Kept = $kept
            Message = "would add $($added.Count) and update $($updated.Count) hook entr(y/ies)"
        }
    }

    # Parse the RESULT before it is allowed anywhere near the file on disk.
    try {
        $null = $merged | ConvertFrom-Json
    } catch {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetPath; Added = $empty; Skipped = $skipped
            Updated = $empty; Differs = $differs
            Message = "the merged result does not parse - abandoned, the live file is untouched"
        }
    }

    # The legacy backup (made once) is kept for the add path. An update always makes its
    # own stamped backup, and a name that exists is never reused.
    $backup = "$TargetPath.bak"
    if ($updated.Count -gt 0) {
        $backup = "$TargetPath.bak-$BackupStamp"
        $counter = 2
        while (Test-Path $backup) { $backup = "$TargetPath.bak-$BackupStamp-$counter"; $counter++ }
        Copy-Item $TargetPath $backup -Force
    } elseif (-not (Test-Path $backup)) {
        Copy-Item $TargetPath $backup -Force
    }
    Write-RtTextNoBom -Path $TargetPath -Text $merged

    # R9 again, and this time it can undo: re-read what is actually on disk, and for an
    # update check that every new value really is there.
    $readBackText = [string](& $ReadBack $TargetPath)
    $parsedBack = $null
    try { $parsedBack = $readBackText | ConvertFrom-Json } catch { $parsedBack = $null }
    $holdsNewValues = $true
    foreach ($literal in $newLiterals) { if (-not $readBackText.Contains($literal)) { $holdsNewValues = $false } }
    if ($null -eq $parsedBack -or -not $holdsNewValues) {
        Copy-Item $backup $TargetPath -Force
        return [PSCustomObject]@{
            Action = "restored"; Path = $TargetPath; Added = $empty; Skipped = $skipped
            Updated = $empty; Differs = $differs
            Message = "what landed on disk did not parse or lacks the new value - restored from $backup"
        }
    }

    return [PSCustomObject]@{
        Action = $(if ($updated.Count -gt 0) { "updated" } else { "merged" }); Path = $TargetPath
        Added = $added; Skipped = $skipped; Updated = $updated; Differs = $differs; Kept = $kept
        Message = "added $($added.Count) and updated $($updated.Count) hook entr(y/ies); every other entry and the env block untouched"
    }
}

# --- ~/.claude/hooks/ -------------------------------------------------------

function Install-RtGlobalHooks {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Deploy the hook scripts a fresh machine has none of. Measured
            2026-08-30: setup.ps1 -All calls install-junctions.ps1 WITHOUT -Sync,
            and that legacy flow contains no hook handling at all, while
            Merge-RtGlobalSettings above happily adds the hook ENTRIES. A student
            therefore ended up with hooks declared in ~/.claude/settings.json and
            no scripts behind them - and a declared hook whose script is absent
            makes the interpreter exit non-zero, which refuses every tool in that
            hook's matcher. That is the 2026-08-27 failure (vault-access-guard.py
            declared and missing, Read/Grep/Bash refused for four turns), except
            reproduced by construction on every machine the toolkit was installed
            on. check-deployment.ps1 already REPORTED it; nothing fixed it.

            The contract matches the two writers above and the reason is the same:
            setup ADDS what is missing and never overwrites what the operator has.
            A hook already present is left byte-identical and reported as differing
            when it differs, because updating a deployed hook is -Sync's job, where
            the copy is gated on the green stamp and the file has been proven by the
            offline suite. Setup runs on a clone that has no stamp, so it may only
            seed what is absent.

        Inputs:
            SourceDir (string): the repository's .claude/hooks
            TargetDir (string): destination, normally ~/.claude/hooks
            Preview (switch): decide and report, write nothing (R16)

        Outputs:
            result (PSCustomObject): Action, Path, Installed, Kept, Differing, Message
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$TargetDir,
        [switch]$Preview
    )

    # Leading commas: an empty array returned from a function unrolls to $null, and
    # "nothing was installed" must stay a list the caller can count.
    $installed = @()
    $kept      = @()
    $differing = @()

    if (-not (Test-Path $SourceDir -PathType Container)) {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetDir
            Installed = $installed; Kept = $kept; Differing = $differing
            Message = "hook source directory not found: $SourceDir"
        }
    }

    # .json travels with .py: a hook whose configuration file did not arrive disables
    # itself in silence (R11), which looks exactly like a hook that is working.
    $files = @(Get-RtHookFiles -HooksDir $SourceDir)
    if ($files.Count -eq 0) {
        return [PSCustomObject]@{
            Action = "noop"; Path = $TargetDir
            Installed = $installed; Kept = $kept; Differing = $differing
            Message = "no hook files to deploy"
        }
    }

    foreach ($file in $files) {
        $destination = Join-Path $TargetDir $file.Name
        if (Test-Path $destination -PathType Leaf) {
            $kept += $file.Name
            $sourceHash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
            $liveHash   = (Get-FileHash -Path $destination  -Algorithm SHA256).Hash
            if ($sourceHash -ne $liveHash) { $differing += $file.Name }
            continue
        }
        $installed += $file.Name
    }

    if ($Preview) {
        return [PSCustomObject]@{
            Action = "preview"; Path = $TargetDir
            Installed = $installed; Kept = $kept; Differing = $differing
            Message = "would install $($installed.Count) absent hook file(s); $($kept.Count) already present, left alone"
        }
    }

    if ($installed.Count -gt 0 -and -not (Test-Path $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    $failed = @()
    foreach ($name in $installed) {
        $source = Join-Path $SourceDir $name
        $destination = Join-Path $TargetDir $name
        Copy-Item $source $destination -Force
        # R9: read back the state that was supposed to change. A copy that reported no
        # error and produced no file is the exact shape of the defect being fixed here.
        if (-not (Test-Path $destination -PathType Leaf)) { $failed += $name }
    }

    if ($failed.Count -gt 0) {
        return [PSCustomObject]@{
            Action = "refused"; Path = $TargetDir
            Installed = @($installed | Where-Object { $failed -notcontains $_ })
            Kept = $kept; Differing = $differing
            Message = "copy reported success but these files are absent: $($failed -join ', ')"
        }
    }

    $message = "installed $($installed.Count) absent hook file(s); $($kept.Count) already present, left untouched"
    if ($differing.Count -gt 0) {
        $message += "; $($differing.Count) differ from the repository (install-junctions.ps1 -Sync updates those): $($differing -join ', ')"
    }
    return [PSCustomObject]@{
        Action = "installed"; Path = $TargetDir
        Installed = $installed; Kept = $kept; Differing = $differing
        Message = $message
    }
}
