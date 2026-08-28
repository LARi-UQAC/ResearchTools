<#
.SYNOPSIS
    The -Sync engine for install-junctions.ps1: keeps ~/.claude in step with the repo.

.DESCRIPTION
    Dot-sourced by install-junctions.ps1 when -Sync is passed. It lives in its own file
    for one reason that matters: the two functions that write ~/.claude/CLAUDE.md and
    ~/.claude/settings.json are the only irreversible things here, and a test must be
    able to load them WITHOUT running the installer's legacy junction-creation flow as a
    side effect. Dot-sourcing install-junctions.ps1 would do exactly that, and would
    write to the real ~/.claude just by being tested.

    Exercised offline by scripts	esterify-sync-writes.ps1, which loads this file and
    drives it against copies in a temporary directory.
#>

# ==============================================================================
# -Sync : keep ~/.claude in step with this repository, and prove what it pushes
# ==============================================================================
#
# -Sync is a DISTINCT code path from the legacy junction-creation flow below, which
# is left exactly as it was. The legacy flow reports EXISTS for a link that has
# silently detached and moves on; that is precisely what let sixteen agents rot, so
# -Sync compares CONTENT and refreshes on mismatch instead.
#
# Three behaviours matter and none is optional, because the usual caller is a
# SessionStart hook firing inside the professor's thesis folder:
#   never elevate       - a UAC prompt mid-writing hangs the session
#   never exit non-zero - a hook that fails refuses every tool of its matcher
#   take a lock         - two projects opening at once would both write settings.json,
#                         and a torn JSON write breaks every session on the machine

$script:RtQuiet   = $false
$script:RtChanged = @()
$script:RtHeld    = @()

function Write-Rt([string]$text, [string]$colour = "Gray") {
    if (-not $script:RtQuiet) { Write-Host $text -ForegroundColor $colour }
}

# --- The green stamp ----------------------------------------------------------
# Written by scripts\test\run-offline-tests.ps1 on a full pass, deleted on any
# failure. Carries a hash PER CODE FILE, so a file untouched since the last green
# run is provably tested and keeps flowing while an edited neighbour is held.
function Get-RtStamp([string]$repoRoot) {
    $p = Join-Path $repoRoot ".rt-green.json"
    if (-not (Test-Path $p -PathType Leaf)) { return $null }
    try { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Test-RtProven($stamp, [string]$repoRoot, [string]$fullPath) {
    if ($null -eq $stamp) { return $false }
    $rel = $fullPath.Substring($repoRoot.Length + 1)
    $entry = $stamp.code_hashes.PSObject.Properties | Where-Object { $_.Name -eq $rel } | Select-Object -First 1
    if ($null -eq $entry) { return $false }
    $actual = (Get-FileHash -Path $fullPath -Algorithm SHA256).Hash
    return ($actual -eq $entry.Value)
}

# --- Shape checks for prose, which has no tests to pass -----------------------
function Test-RtAgentShape([string]$path) {
    try { $head = Get-Content $path -TotalCount 25 -ErrorAction Stop } catch { return $false }
    if ($head.Count -lt 3) { return $false }
    if ($head[0].Trim() -ne "---") { return $false }
    $joined = ($head -join "`n")
    if ($joined -notmatch "(?m)^name:\s*\S")        { return $false }
    if ($joined -notmatch "(?m)^description:\s*\S") { return $false }
    return $true
}

function Test-RtSkillShape([string]$dir) {
    $skill = Join-Path $dir "SKILL.md"
    if (-not (Test-Path $skill -PathType Leaf)) { return $false }
    return ((Get-Item $skill).Length -gt 0)
}

# --- Refresh on mismatch ------------------------------------------------------
# A copy is honest about being a copy: it cannot masquerade as a link the way a
# detached hardlink did. Content is re-checked on every run, so a stale copy is
# repaired next time rather than surviving unnoticed.
function Sync-RtFile([string]$src, [string]$dst, [string]$label) {
    if (Test-Path $dst) {
        $item = Get-Item $dst -Force
        if ($item.PSIsContainer) {
            Write-Rt "  [CONFLICT] $label is a directory - not touching" "Red"
            return
        }
        $same = $false
        try {
            $same = ((Get-FileHash $dst -Algorithm SHA256).Hash -eq (Get-FileHash $src -Algorithm SHA256).Hash)
        } catch { $same = $false }
        if ($same) { return }
        Remove-Item $dst -Force -ErrorAction SilentlyContinue
    }
    $parent = Split-Path $dst -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    try {
        New-Item -ItemType SymbolicLink -Path $dst -Target $src -ErrorAction Stop | Out-Null
    } catch {
        # No symlink privilege. Copy rather than elevate: a UAC prompt would hang a
        # session that is in the middle of someone's thesis.
        Copy-Item -Path $src -Destination $dst -Force
    }
    $script:RtChanged += $label
    Write-Rt "  [SYNCED]   $label" "Green"
}

function Sync-RtSkill([string]$srcDir, [string]$dstDir, [string]$name) {
    if (Test-Path $dstDir) {
        $item = Get-Item $dstDir -Force
        if ($item.LinkType -ne "Junction") {
            Write-Rt "  [CONFLICT] skills\$name is a real directory - not touching" "Red"
        }
        return
    }
    if (-not (Test-RtSkillShape $srcDir)) {
        $script:RtHeld += "skills\$name"
        Write-Rt "  [HELD]     skills\$name (no usable SKILL.md)" "Yellow"
        return
    }
    New-Item -ItemType Junction -Path $dstDir -Target $srcDir | Out-Null
    $script:RtChanged += "skills\$name"
    Write-Rt "  [SYNCED]   skills\$name (new junction)" "Green"
}

# --- ~/.claude/CLAUDE.md : the contract block, between markers ----------------
# The block's single source of truth is CLAUDE.template.md; this copies it
# marker-to-marker. Everything outside the markers in the live file is untouched,
# so re-running is idempotent.
function Update-RtClaudeMd([string]$repoRoot, [string]$homeClaude) {
    $begin = "<!-- RT-CONTRACT:BEGIN -->"
    $end   = "<!-- RT-CONTRACT:END -->"

    $tmplPath = Join-Path $repoRoot "CLAUDE.template.md"
    if (-not (Test-Path $tmplPath)) { return }
    $tmpl = Get-Content $tmplPath -Raw -Encoding UTF8

    $bi = $tmpl.IndexOf($begin)
    $ei = $tmpl.IndexOf($end)
    if ($bi -lt 0 -or $ei -lt 0 -or $ei -lt $bi) { return }
    $block = $tmpl.Substring($bi, $ei - $bi + $end.Length)

    $livePath = Join-Path $homeClaude "CLAUDE.md"
    if (-not (Test-Path $livePath -PathType Leaf)) { return }
    $live = Get-Content $livePath -Raw -Encoding UTF8

    $lbi = $live.IndexOf($begin)
    $lei = $live.IndexOf($end)

    # A BEGIN without its END, or the reverse, means someone edited by hand and left
    # it malformed. Report and change nothing: guessing where the block ends risks
    # eating the professor's own content.
    if (($lbi -ge 0) -ne ($lei -ge 0)) {
        Write-Rt "  [CONFLICT] ~/.claude/CLAUDE.md has an unmatched RT-CONTRACT marker - not touching" "Red"
        return
    }

    if ($lbi -ge 0) {
        $current = $live.Substring($lbi, $lei - $lbi + $end.Length)
        if ($current -eq $block) { return }
        $updated = $live.Substring(0, $lbi) + $block + $live.Substring($lei + $end.Length)
    } else {
        $updated = $live.TrimEnd() + "`r`n`r`n" + $block + "`r`n"
    }

    $bak = "$livePath.bak"
    if (-not (Test-Path $bak)) { Copy-Item $livePath $bak -Force }
    Set-Content -Path $livePath -Value $updated -Encoding utf8 -NoNewline
    $script:RtChanged += "CLAUDE.md contract block"
    Write-Rt "  [SYNCED]   ~/.claude/CLAUDE.md contract block" "Green"
}

# --- ~/.claude/settings.json : one idempotent SessionStart entry --------------
# Inserted as TEXT, not by reserialising the parsed object. ConvertTo-Json would
# rewrite the whole file's formatting; a targeted insertion leaves every existing
# entry and the env block byte-for-byte identical. Parsed before and after, so a
# malformed result is abandoned rather than shipped.
function Update-RtSettings([string]$repoRoot, [string]$homeClaude) {
    $path = Join-Path $homeClaude "settings.json"
    if (-not (Test-Path $path -PathType Leaf)) { return }

    $raw = Get-Content $path -Raw -Encoding UTF8
    try { $null = $raw | ConvertFrom-Json } catch {
        Write-Rt "  [CONFLICT] ~/.claude/settings.json does not parse - not touching" "Red"
        return
    }

    if ($raw.Contains("install-junctions.ps1")) { return }

    $anchor = '"SessionStart": ['
    $ai = $raw.IndexOf($anchor)
    if ($ai -lt 0) {
        Write-Rt "  [CONFLICT] no SessionStart array in settings.json - not touching" "Red"
        return
    }

    # -Command, not -File: if the repository is ever moved or renamed, the command
    # still exits 0 in silence, as the safety law requires of any hook.
    $script  = Join-Path $repoRoot "install-junctions.ps1"
    $q       = [string][char]34   # a string, not a char: .Replace(char,char) cannot take a 2-char replacement
    $inner   = "if (Test-Path '$script') { & '$script' -Sync -Quiet }; exit 0"
    $command = "powershell -NoProfile -ExecutionPolicy Bypass -Command " + $q + $inner + $q
    $jsonCmd = $command.Replace('\', '\\').Replace($q, '\' + $q)

    $nl = "`r`n"
    $entry = $nl + '      {' +
             $nl + '        "hooks": [' +
             $nl + '          {' +
             $nl + '            "type": "command",' +
             $nl + '            "command": "' + $jsonCmd + '",' +
             $nl + '            "timeout": 30,' +
             $nl + '            "statusMessage": "Syncing ResearchTools..."' +
             $nl + '          }' +
             $nl + '        ]' +
             $nl + '      },'

    $updated = $raw.Insert($ai + $anchor.Length, $entry)
    try { $null = $updated | ConvertFrom-Json } catch {
        Write-Rt "  [CONFLICT] insertion would have broken settings.json - abandoned" "Red"
        return
    }

    $bak = "$path.bak"
    if (-not (Test-Path $bak)) { Copy-Item $path $bak -Force }
    Set-Content -Path $path -Value $updated -Encoding utf8 -NoNewline
    $script:RtChanged += "settings.json SessionStart entry"
    Write-Rt "  [SYNCED]   ~/.claude/settings.json SessionStart entry" "Green"
}

# --- .rt-undo pruning ---------------------------------------------------------
# Runs on every sync regardless of what was held, so pruning is never skipped as a
# side effect of code being unproven.
function Remove-RtUndoExcess([string]$repoRoot, [int]$keep = 20) {
    $undo = Join-Path $repoRoot ".rt-undo"
    if (-not (Test-Path $undo)) { return }
    Get-ChildItem $undo -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $keep |
        ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
}

function Invoke-RtSync([string]$repoRoot, [string]$homeClaude) {
    $lock = Join-Path $homeClaude ".rt-sync.lock"
    if (Test-Path $lock) {
        $age = (Get-Date) - (Get-Item $lock).LastWriteTime
        if ($age.TotalSeconds -lt 60) { return }   # another session is syncing
    }
    New-Item -ItemType File -Path $lock -Force | Out-Null

    try {
        $repoClaude = Join-Path $repoRoot ".claude"
        $stamp = Get-RtStamp $repoRoot

        Write-Rt ""
        Write-Rt "=== ResearchTools sync ===" "Cyan"
        if ($null -eq $stamp) {
            Write-Rt "  No green stamp - code is held until the test suite passes." "Yellow"
        }

        # Agents: prose, gated on shape.
        $agentsSrc = Join-Path $repoClaude "agents"
        if (Test-Path $agentsSrc) {
            Get-ChildItem $agentsSrc -File -Filter *.md | ForEach-Object {
                if (Test-RtAgentShape $_.FullName) {
                    Sync-RtFile $_.FullName (Join-Path $homeClaude "agents\$($_.Name)") "agents\$($_.Name)"
                } else {
                    $script:RtHeld += "agents\$($_.Name)"
                    Write-Rt "  [HELD]     agents\$($_.Name) (frontmatter incomplete)" "Yellow"
                }
            }
        }

        # Skills: existing folders are junctions and are already live; only a NEW
        # skill needs a junction, and that is gated on SKILL.md being usable.
        $skillsSrc = Join-Path $repoClaude "skills"
        if (Test-Path $skillsSrc) {
            Get-ChildItem $skillsSrc -Directory | ForEach-Object {
                Sync-RtSkill $_.FullName (Join-Path $homeClaude "skills\$($_.Name)") $_.Name
            }
        }

        # Hooks: per-file only. ~/.claude/hooks holds six hooks that are not in this
        # repo, and a directory junction would shadow them - a hook whose script is
        # absent refuses every tool of its matcher. Gated on the green stamp.
        $hooksSrc = Join-Path $repoClaude "hooks"
        if (Test-Path $hooksSrc) {
            Get-ChildItem $hooksSrc -File -Filter *.py | ForEach-Object {
                if (Test-RtProven $stamp $repoRoot $_.FullName) {
                    Sync-RtFile $_.FullName (Join-Path $homeClaude "hooks\$($_.Name)") "hooks\$($_.Name)"
                } else {
                    $script:RtHeld += "hooks\$($_.Name)"
                    Write-Rt "  [HELD]     hooks\$($_.Name) (changed since last green run)" "Yellow"
                }
            }
        }

        Update-RtClaudeMd $repoRoot $homeClaude
        Update-RtSettings $repoRoot $homeClaude
        Remove-RtUndoExcess $repoRoot

        if ($script:RtQuiet) {
            # SessionStart stdout becomes context, so silence when clean is what keeps
            # this free; one line when something moved doubles as the professor's
            # notice that the toolkit changed under them.
            if ($script:RtChanged.Count -gt 0 -or $script:RtHeld.Count -gt 0) {
                $msg = "[RT-SYNC] $($script:RtChanged.Count) synced"
                if ($script:RtHeld.Count -gt 0) { $msg += ", $($script:RtHeld.Count) held (untested or malformed)" }
                Write-Host $msg
            }
        } else {
            Write-Rt ""
            Write-Rt "  synced $($script:RtChanged.Count)   held $($script:RtHeld.Count)" "Cyan"
            Write-Rt ""
        }
    }
    finally {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
    }
}

