<#
.SYNOPSIS
    Install the global privacy-guard git hooks (core.hooksPath) for every repository on this machine.

.DESCRIPTION
    Copies pre-commit and privacy-rules.toml to -Target, copies _chain there under every other
    client-side hook name (so each repository's own .git/hooks keep running, since a global
    core.hooksPath disables them), then sets `git config --global core.hooksPath` to -Target and
    reads it back (R9). A global core.hooksPath already pointing elsewhere is REFUSED rather than
    overwritten: another hook manager owns it. -Uninstall unsets core.hooksPath when it points to
    -Target and leaves the files. Prints a human summary and, with -Json, one JSON object (R17).

.PARAMETER Target
    Directory the hooks are installed into. Default: ~/.config/git/hooks.

.PARAMETER DryRun
    Print what would be done and change nothing (R16).

.PARAMETER Uninstall
    Unset the global core.hooksPath if it points to -Target.

.PARAMETER Json
    Also print the machine-readable report.

.PARAMETER TermsFrom
    Directories whose subfolders name real people (for example a folder of student projects).
    The names found -TermsDepth levels below each one, split at capital letters, become the
    machine-local deny list `private-terms.txt` in -Target, which the hooks refuse in any
    added line, file path or commit message. Run it once for every NEW student: the list is
    only ever APPENDED to (the terms the file lacks, case ignored), never rewritten, so a name
    that left the disk, a line typed by hand and the bytes already there all survive; remove a
    name by editing the file. It is never committed; terms typed by hand may also go to
    `private-terms.extra.txt`, which this script never touches. Only COUNTS are printed, never
    a term. Ordinary words listed in deny-term-stopwords.txt are set aside in
    `private-terms.excluded.txt` (a real surname goes in the extra file), the ASCII-folded
    spelling of an accented name is added, and a folder yielding nothing is refused. The list
    holds real names, so the run is REFUSED (exit 2, nothing written, dry run included) when
    -Target, a parent or a junction target is synchronized or shared; the message names the
    category, never the path. The three file names are added to the global git ignore
    (core.excludesFile, else <XDG_CONFIG_HOME or ~/.config>/git/ignore).

.PARAMETER TermsDepth
    How many levels below each -TermsFrom directory the person folders sit. Default 2.

.OUTPUTS
    Exit 0 done (or dry run), 2 refused by design (another core.hooksPath, missing source file),
    1 failure (the read-back does not match what was written).
#>
param(
    [string]$Target = (Join-Path $HOME ".config\git\hooks"),
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$Json,
    [string[]]$TermsFrom = @(),
    [int]$TermsDepth = 2
)

$ErrorActionPreference = "Stop"

# A relative -Target is resolved against PowerShell's own location, which is where Copy-Item and
# New-Item write. [IO.Path]::GetFullPath alone uses the process directory, a different place
# after a Set-Location, so the synchronized-folder check could judge the wrong folder.
if (-not [System.IO.Path]::IsPathRooted($Target)) { $Target = Join-Path $PWD.ProviderPath $Target }

# Files that make up the extra scan, copied beside the hooks. privacy-guard.conf owns the
# shortest deny-list term (one owner for the installer and the hook, R0).
$ExtraFiles = @("privacy-lib.sh", "privacy-extra.awk", "fixture-path-allow.txt", "privacy-guard.conf")
# Installer-only data, read from the source folder and not copied: ordinary words that are
# never written into a generated deny list.
$StopwordsFile = "deny-term-stopwords.txt"

# Every hook name githooks(5) documents (git 2.53), minus the privacy hooks and the two
# below. _chain stands in for the rest so a repository's own .git/hooks keep running under
# a global core.hooksPath. The privacy script itself is installed as pre-commit AND as
# pre-merge-commit, since a clean merge runs only the latter and could otherwise carry new
# content in unchecked; it chains to the repository's hook of its own name. pre-push has its
# own script: it scans every outgoing commit (--no-verify, cherry-pick, rebase never ran
# pre-commit) and chains the repository's pre-push with the same stdin.
$PrivacyHookNames = @("pre-commit", "pre-merge-commit")
$ChainNames = @(
    "applypatch-msg", "pre-applypatch", "post-applypatch",
    "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout",
    "post-merge", "pre-receive", "update", "proc-receive", "post-receive",
    "post-update", "push-to-checkout", "pre-auto-gc", "post-rewrite", "sendemail-validate",
    "fsmonitor-watchman", "p4-changelist", "p4-prepare-changelist", "p4-post-changelist",
    "p4-pre-submit"
)
# NOT chained, deliberately: they fire several times per ordinary command, and a chain
# script spawns a shell each time. Measured 2026-10-02 on Windows: 10 add+commit+status
# cycles took 575 ms each with no hook, 3598 ms with these two chained. A repository's own
# copy of either one does not run while the guard is installed. Do NOT work around this with
# a local core.hooksPath: a repo-local value overrides the global one and switches the
# privacy guard off for that repository entirely.
$ExcludedHooks = @("reference-transaction", "post-index-change")
# A file in -Target is ours when it carries one of these markers; anything else belongs to
# another hook manager and is never overwritten.
$OwnMarkers = @("installed by install-git-hooks.ps1", 'title = "LARi privacy guard"')

function Get-NormalPath([string]$Path) {
    <# Purpose: compare two spellings of one directory. Inputs: Path. Outputs: full path, forward slashes, no trailing slash. #>
    if (-not $Path) { return "" }
    return ([System.IO.Path]::GetFullPath($Path) -replace '\\', '/').TrimEnd('/')
}

# Windows cloud-file attributes (winnt.h): OFFLINE 0x1000, RECALL_ON_OPEN 0x40000, PINNED 0x80000,
# UNPINNED 0x100000, RECALL_ON_DATA_ACCESS 0x400000. A OneDrive placeholder carries one of them
# whatever its path is called. Specified by the Win32 header, not measured here (R4); this branch
# has no offline test, since a test cannot create a cloud placeholder (R15: marked unverified).
$CloudAttributeMask = 0x1000 -bor 0x40000 -bor 0x80000 -bor 0x100000 -bor 0x400000

function Get-SyncMarkers([string]$Path) {
    <# Purpose: read the synchronized-folder names. Inputs: Path of sync-folder-markers.txt.
       Outputs: lowercase names. Raises: a missing file stops the run and names it (R3). #>
    # The file NAME only: a path carries the account name, and this message can reach a log.
    if (-not (Test-Path -LiteralPath $Path)) { throw "missing configuration file: $(Split-Path -Leaf $Path)" }
    # Trimmed BEFORE the emptiness test: a whitespace-only line would otherwise become an
    # empty marker that matches every segment starting with a space, dash or underscore.
    return @(Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object { $_.Trim().ToLowerInvariant() } |
             Where-Object { $_ -and -not $_.StartsWith("#") })
}

function Test-InsideRoot([string]$Candidate, [string]$Root) {
    <# Purpose: is Candidate equal to or below Root. Inputs: two paths. Outputs: bool. #>
    if (-not $Root) { return $false }
    $c = ([System.IO.Path]::GetFullPath($Candidate) -replace '\\', '/').TrimEnd('/').ToLowerInvariant()
    $r = ([System.IO.Path]::GetFullPath($Root) -replace '\\', '/').TrimEnd('/').ToLowerInvariant()
    return ($c -eq $r) -or $c.StartsWith($r + "/")
}

function Test-SyncedFolder([string]$Path, [string[]]$Markers) {
    <# Purpose: tell whether a folder, one of its parents, or the real target of a junction or symbolic link among them
       is synchronized to a cloud service or sits on a network share, where the deny list would leave this machine.
       Inputs: Path, Markers (synchronized-folder names). Outputs: a short reason naming the CATEGORY, never the path
       (a path carries the account name), or $null when nothing points to synchronization. #>
    $full = [System.IO.Path]::GetFullPath($Path)
    # Decided on the string: a filesystem call on an unreachable share can hang for a long time (R10).
    if ($full.StartsWith("\\")) { return "network (UNC) location" }
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add($full)
    $cur = $full
    while ($cur) {
        if (Test-Path -LiteralPath $cur) {
            $item = Get-Item -LiteralPath $cur -Force -ErrorAction SilentlyContinue
            if ($item) {
                if ([int]$item.Attributes -band $CloudAttributeMask) { return "cloud-file attribute on the folder or a parent" }
                if ($item.LinkType) {
                    foreach ($t in @($item.Target)) {
                        if ($t) { $candidates.Add([System.IO.Path]::GetFullPath([string]$t)) }
                    }
                }
            }
        }
        $parent = Split-Path -Path $cur -Parent
        if (-not $parent -or $parent -eq $cur) { break }
        $cur = $parent
    }
    $roots = @("OneDrive", "OneDriveConsumer", "OneDriveCommercial") | ForEach-Object { [Environment]::GetEnvironmentVariable($_) }
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        $info = if ($base) { Join-Path $base "Dropbox\info.json" } else { $null }
        if ($info -and (Test-Path -LiteralPath $info)) {
            try {
                $json = Get-Content -LiteralPath $info -Raw -Encoding UTF8 | ConvertFrom-Json
                foreach ($acct in $json.PSObject.Properties) { if ($acct.Value.path) { $roots += [string]$acct.Value.path } }
            } catch { }
        }
    }
    foreach ($c in $candidates) {
        # A junction or symbolic link can point at a share, so every candidate is tested, not only $Path.
        if ($c.StartsWith("\\")) { return "network (UNC) location" }
        # A mapped drive letter (H:) is a share too. Unverified offline: a test cannot map a network drive (R15).
        try {
            $driveRoot = [System.IO.Path]::GetPathRoot($c)
            if ($driveRoot -and ([System.IO.DriveInfo]::new($driveRoot)).DriveType -eq [System.IO.DriveType]::Network) { return "mapped network drive" }
        } catch { }
        foreach ($r in $roots) { if (Test-InsideRoot $c $r) { return "folder of a synchronization client" } }
        foreach ($segment in ($c -split '[\\/]')) {
            $low = $segment.ToLowerInvariant()
            foreach ($m in $Markers) {
                # "=name" is an exact folder name, a plain name is a prefix ended by space, dash, underscore or the end.
                $hit = if ($m.StartsWith("=")) { $low -eq $m.Substring(1) } else { $low -match ("^" + [regex]::Escape($m) + '($|[\s_-])') }
                if ($hit) { return "synchronized folder named '$($m.TrimStart('='))'" }
            }
        }
    }
    return $null
}

function Add-GlobalIgnore([string[]]$Patterns) {
    <# Purpose: add the deny-list file names to the global git excludes file, so a copy of the list dropped into any
       repository cannot be staged by accident (a second protection, the hooks being the first).
       Inputs: Patterns (file names). Outputs: number of patterns added. The file is core.excludesFile when set,
       else <XDG_CONFIG_HOME or ~/.config>/git/ignore, which git reads by default. Read back after writing (R9).
       Raises: when a pattern is absent after the write. #>
    $file = (& git config --global --get core.excludesFile 2>$null)
    if ($file -and $file.StartsWith("~")) { $file = Join-Path $HOME $file.Substring(1).TrimStart('/', '\') }
    if (-not $file) {
        $base = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $HOME ".config" }
        $file = Join-Path $base "git\ignore"
    }
    $have = @()
    if (Test-Path -LiteralPath $file) { $have = @(Get-Content -LiteralPath $file -Encoding UTF8 | ForEach-Object { $_.Trim() }) }
    $missing = @($Patterns | Where-Object { $have -notcontains $_ })
    if ($missing.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Path $file -Parent) | Out-Null
        $text = if (Test-Path -LiteralPath $file) { Get-Content -LiteralPath $file -Raw -Encoding UTF8 } else { "" }
        if ($text -and -not $text.EndsWith("`n")) { $text += "`n" }
        $text += "# Privacy guard: the machine-local deny list is never a repository file.`n" + ($missing -join "`n") + "`n"
        [System.IO.File]::WriteAllText($file, $text, (New-Object System.Text.UTF8Encoding($false)))
    }
    $after = @(Get-Content -LiteralPath $file -Encoding UTF8 | ForEach-Object { $_.Trim() })
    foreach ($p in $Patterns) { if ($after -notcontains $p) { throw "global ignore read-back mismatch" } }
    return $missing.Count
}

function Get-KnownTerms([string]$Path) {
    <# Purpose: the terms a list file already holds. Inputs: Path (may be absent). Outputs: a case-insensitive
       HashSet of trimmed, non-comment lines (a leading byte order mark is ignored). #>
    $known = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    if (Test-Path -LiteralPath $Path) {
        foreach ($l in ([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) -split "\r?\n")) {
            $t = $l.Trim().TrimStart([char]0xFEFF)
            if ($t -and -not $t.StartsWith("#")) { [void]$known.Add($t) }
        }
    }
    return ,$known
}

function Add-NewTerms([string]$Path, [string[]]$Terms, [string]$Header) {
    <# Purpose: APPEND the terms a list file does not hold yet. The file is created with Header when absent and
       is otherwise never rewritten: its bytes stay as they were, so a name that left the disk, a line typed by
       hand and a graduated student all survive a run (the owner runs this once per new student).
       Inputs: Path, Terms (candidate terms), Header (comment block for a new file).
       Outputs: number of terms appended. Raises: when a term is absent after the write (R9). #>
    $known = Get-KnownTerms $Path
    $new = @($Terms | Where-Object { $_ -and -not $known.Contains($_) })
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if (-not (Test-Path -LiteralPath $Path)) {
        [System.IO.File]::WriteAllText($Path, $Header + ($new -join "`n") + $(if ($new.Count -gt 0) { "`n" } else { "" }), $utf8)
    } elseif ($new.Count -gt 0) {
        $existing = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        $lead = if ($existing.Length -gt 0 -and -not $existing.EndsWith("`n")) { "`n" } else { "" }
        [System.IO.File]::AppendAllText($Path, $lead + ($new -join "`n") + "`n", $utf8)
    }
    $after = Get-KnownTerms $Path
    foreach ($t in $Terms) { if ($t -and -not $after.Contains($t)) { throw "deny list read-back mismatch" } }
    return $new.Count
}

function Write-Report([hashtable]$Report, [int]$Code) {
    <# Purpose: print the human summary and the optional JSON, then exit. Inputs: report, exit code. #>
    Write-Host ("privacy guard hooks: {0} - {1}" -f $Report.status, $Report.message)
    if ($Json) { $Report | ConvertTo-Json -Depth 4 }
    exit $Code
}

$source  = $PSScriptRoot
$targetN = Get-NormalPath $Target
$current = (& git config --global --includes --get core.hooksPath 2>$null)
$currentN = Get-NormalPath $current
$report = @{ target = $targetN; previous_hooks_path = $current; dry_run = [bool]$DryRun; files = @();
             not_chained = $ExcludedHooks }

if ($Uninstall) {
    if ($currentN -ne $targetN) {
        $report.status = "unchanged"; $report.message = "core.hooksPath does not point to $targetN"
        Write-Report $report 0
    }
    if ($DryRun) {
        $report.status = "dry-run"; $report.message = "would unset core.hooksPath; files would stay in $targetN"
        Write-Report $report 0
    }
    & git config --global --unset core.hooksPath
    # R9: a native command's failure does not throw in PowerShell; read the effect back.
    if (Get-NormalPath (& git config --global --includes --get core.hooksPath 2>$null)) {
        $report.status = "failed"; $report.message = "core.hooksPath is still set after --unset"
        Write-Report $report 1
    }
    $report.status = "uninstalled"
    $report.message = "core.hooksPath unset; files left in $targetN"
    Write-Report $report 0
}

if ($current -and $currentN -ne $targetN) {
    $report.status = "refused"
    $report.message = "global core.hooksPath already points to $current; not overwritten"
    Write-Report $report 2
}

# The deny list holds real names: it must never be written where a sync client or a network
# share would copy it off this machine. Decided before anything is written, dry run included.
try { $syncMarkers = Get-SyncMarkers (Join-Path $source "sync-folder-markers.txt") }
catch { $report.status = "refused"; $report.message = $_.Exception.Message; Write-Report $report 2 }
$syncReason = Test-SyncedFolder $Target $syncMarkers
if ($syncReason -and $TermsFrom.Count -gt 0) {
    $report.status = "refused"; $report.sync_reason = $syncReason
    # The JSON report carries the path of the target, and that path holds the account name.
    $report.Remove("target"); $report.Remove("previous_hooks_path")
    $report.message = "REFUSED, nothing written: the hooks folder is in a synchronized or shared location ($syncReason), " +
        "so the deny list of real names would be copied off this machine. Move the guard to a local folder that nothing " +
        "synchronizes: run -Uninstall, then run this command again with -Target <local folder>."
    Write-Report $report 2
}

foreach ($name in (@("pre-commit", "pre-push", "_chain", "privacy-rules.toml") + $ExtraFiles)) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $name))) {
        $report.status = "refused"; $report.message = "source file missing: $name"
        Write-Report $report 2
    }
}
foreach ($dir in $TermsFrom) {
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        $report.status = "refused"; $report.message = "-TermsFrom directory not found"
        Write-Report $report 2
    }
}

function Get-ConfValue([string]$Path, [string]$Key) {
    <# Purpose: read one key=value line of privacy-guard.conf. Inputs: Path, Key. Outputs: the value string.
       Raises: a missing file or key stops the run and names both (R3), never a silent default. #>
    $leaf = Split-Path -Leaf $Path   # never the full path: it carries the account name
    if (-not (Test-Path -LiteralPath $Path)) { throw "missing configuration file: $leaf" }
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) { throw "key '$Key' missing from $leaf" }
    return ($line -replace "^$([regex]::Escape($Key))=", '').Trim()
}

function Get-FoldedName([string]$Text) {
    <# Purpose: spelling of a name without diacritics (Jeremie for Jeremie with accents), so the
       list also catches the way a name is typed on a keyboard that has none.
       Inputs: Text. Outputs: the decomposed string with combining marks removed. #>
    return ($Text.Normalize([System.Text.NormalizationForm]::FormD) -replace '\p{Mn}', '')
}

function Get-DenyTerms([string[]]$Roots, [int]$Depth, [int]$MinLength, [string[]]$Stopwords) {
    <# Purpose: person-folder names under each root, split at capitals, with their ASCII-folded spelling.
       Inputs: Roots (directories), Depth (levels below a root), MinLength (shortest term kept, from the
       effective privacyguard floor), Stopwords (ordinary words never written).
       Outputs: hashtable Terms (sorted unique, none purely numeric) and Dropped (the stopwords set aside, sorted). #>
    $found = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    $stop = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($w in $Stopwords) { [void]$stop.Add($w) }
    $dropped = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($root in $Roots) {
        $level = @((Get-Item -LiteralPath $root))
        for ($i = 0; $i -lt $Depth; $i++) {
            $level = @($level | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Directory -ErrorAction SilentlyContinue })
        }
        foreach ($d in $level) {
            $whole = $d.Name -replace '[\s._-]+', ''
            # -csplit: the plain -split is case-insensitive, which would cut at every letter.
            $parts = @($d.Name -csplit '(?<=\p{Ll})(?=\p{Lu})|[\s._-]+')
            foreach ($t in (@($whole) + $parts)) {
                foreach ($v in @($t, (Get-FoldedName $t))) {
                    # A leading '#' would make the line a comment the hook skips; an empty fragment is nothing.
                    $v = $v.TrimStart('#')
                    if (-not $v -or $v -match '^\d+$') { continue }
                    # A fragment under the floor is set aside for review, never skipped unseen
                    # (a short surname such as Kim or Li would otherwise leave no trace).
                    if ($v.Length -lt $MinLength) { [void]$dropped.Add($v); continue }
                    if ($stop.Contains($v) -or $stop.Contains((Get-FoldedName $v))) { [void]$dropped.Add($v); continue }
                    [void]$found.Add($v)
                }
            }
        }
    }
    return @{ Terms = @($found | Sort-Object); Dropped = @($dropped | Sort-Object) }
}

$plan = @(
    @{ from = "privacy-rules.toml"; to = "privacy-rules.toml" }
) + ($ExtraFiles | ForEach-Object { @{ from = $_; to = $_ } }) + ($PrivacyHookNames | ForEach-Object { @{ from = "pre-commit"; to = $_ } }) + @(
    @{ from = "pre-push"; to = "pre-push" }
) + ($ChainNames | ForEach-Object { @{ from = "_chain"; to = $_ } })
$report.files = $plan | ForEach-Object { $_.to }

# Path equality with core.hooksPath does not prove this guard owns the directory: another
# manager may already keep its hooks there. Refuse before writing anything.
$foreign = @($plan | Where-Object {
    $dest = Join-Path $Target $_.to
    if (-not (Test-Path -LiteralPath $dest)) { return $false }
    $text = Get-Content -LiteralPath $dest -Raw -ErrorAction SilentlyContinue
    -not ($OwnMarkers | Where-Object { $text -and $text.Contains($_) })
} | ForEach-Object { $_.to })
if ($foreign.Count -gt 0) {
    $report.status = "refused"; $report.foreign_files = $foreign
    $report.message = "$targetN already holds hooks this guard did not install: $($foreign -join ', ')"
    Write-Report $report 2
}

$bl = Get-Command betterleaks -ErrorAction SilentlyContinue
if (-not $bl) {
    $bl = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Filter betterleaks.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}
$report.betterleaks = [bool]$bl

$terms = @()
$setAside = @()
$termsFile = Join-Path $Target "private-terms.txt"
$reviewFile = Join-Path $Target "private-terms.excluded.txt"
if ($TermsFrom.Count -gt 0 -and (Test-Path -LiteralPath $termsFile)) {
    # UTF-16 (a BOM, or NUL bytes) is unreadable to the hooks: refuse rather than append UTF-8
    # bytes to it and make the whole file garbage.
    $raw = [System.IO.File]::ReadAllBytes($termsFile)
    if (($raw.Length -ge 2 -and (($raw[0] -eq 0xFF -and $raw[1] -eq 0xFE) -or ($raw[0] -eq 0xFE -and $raw[1] -eq 0xFF))) -or ($raw -contains 0)) {
        $report.status = "refused"
        $report.message = "private-terms.txt is UTF-16, which the hooks cannot read; save it as UTF-8 or delete it, nothing written"
        Write-Report $report 2
    }
}
$knownBefore = Get-KnownTerms $termsFile
if ($TermsFrom.Count -gt 0) {
    # The floor is the one the hook will apply: the global git config when set, else the
    # shared default. A value that is not a whole number is refused (R3), not guessed.
    $floorText = (& git config --global --get privacyguard.minTermLength 2>$null)
    try {
        if (-not $floorText) { $floorText = Get-ConfValue (Join-Path $source "privacy-guard.conf") "min_term_length" }
        $stopwords = @(Get-Content -LiteralPath (Join-Path $source $StopwordsFile) -Encoding UTF8 -ErrorAction Stop |
                       Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object { $_.Trim() })
    } catch {
        $report.status = "refused"; $report.message = $_.Exception.Message
        Write-Report $report 2
    }
    $floor = 0
    if (-not [int]::TryParse("$floorText".Trim(), [ref]$floor) -or $floor -lt 1) {
        $report.status = "refused"; $report.message = "privacyguard.minTermLength is not a positive whole number"
        Write-Report $report 2
    }
    $generated = Get-DenyTerms $TermsFrom $TermsDepth $floor $stopwords
    $terms = @($generated.Terms)
    $setAside = @($generated.Dropped)
    if ($terms.Count -eq 0) {
        # A folder that yields nothing is almost always the wrong folder or the wrong depth.
        $report.status = "refused"
        $report.message = "no person folder yielded a usable term at -TermsDepth $TermsDepth; the list is untouched"
        Write-Report $report 2
    }
}
$newTerms = @($terms | Where-Object { -not $knownBefore.Contains($_) })
$report.deny_terms = $knownBefore.Count + $newTerms.Count
$report.added_terms = $newTerms.Count
$report.set_aside_words = $setAside.Count

if ($DryRun) {
    $report.status = "dry-run"
    $report.message = "would copy $($plan.Count) files to $targetN, append $($newTerms.Count) new deny-list terms ($($report.deny_terms) in total) and set global core.hooksPath"
    Write-Report $report 0
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
foreach ($step in $plan) {
    Copy-Item -LiteralPath (Join-Path $source $step.from) -Destination (Join-Path $Target $step.to) -Force
}
$addedNow = 0
if ($TermsFrom.Count -gt 0) {
    $header = "# Machine-local privacy deny list, generated by install-git-hooks.ps1 -TermsFrom. Never commit it.`n" +
              "# New student names are APPENDED at each run, nothing here is ever rewritten or removed by the installer:`n" +
              "# edit this file by hand to remove a name. Terms typed by hand may also go in private-terms.extra.txt.`n"
    $reviewHeader = "# Folder fragments the installer set aside: ordinary words (deny-term-stopwords.txt) or shorter than the floor.`n" +
                    "# If one of them is a real surname, copy it into private-terms.extra.txt. Machine-local, never commit it.`n"
    try {
        $addedNow = Add-NewTerms $termsFile $terms $header          # R9 read-back inside
        if ($setAside.Count -gt 0) { [void](Add-NewTerms $reviewFile $setAside $reviewHeader) }
        $report.ignore_patterns_added = Add-GlobalIgnore @("private-terms.txt", "private-terms.extra.txt", "private-terms.excluded.txt")
    } catch { $report.status = "failed"; $report.message = $_.Exception.Message; Write-Report $report 1 }
}
$totalTerms = (Get-KnownTerms $termsFile).Count
$hasTerms = (Test-Path -LiteralPath $termsFile) -or (Test-Path -LiteralPath (Join-Path $Target "private-terms.extra.txt"))
& git config --global core.hooksPath $targetN

# R9: verify the effect, not the exit codes.
$after = Get-NormalPath (& git config --global --includes --get core.hooksPath)
$bad = $plan | Where-Object {
    (Get-FileHash -LiteralPath (Join-Path $Target $_.to)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $source $_.from)).Hash
}
if ($after -ne $targetN -or $bad) {
    $report.status = "failed"; $report.message = "read-back mismatch (core.hooksPath=$after, files differing: $($bad.Count))"
    Write-Report $report 1
}
$report.status = "installed"
$report.deny_terms = $totalTerms
$report.added_terms = $addedNow
$report.message = "$($plan.Count) files in $targetN; core.hooksPath set; $totalTerms deny-list terms ($addedNow added)" +
    $(if ($setAside.Count -gt 0) { "; $($setAside.Count) fragments set aside (common words or shorter than the floor) in private-terms.excluded.txt, a real surname among them goes in private-terms.extra.txt" } else { "" }) +
    $(if (-not $bl) { "; WARNING betterleaks not found, only the account-name and deny-list checks will run" } else { "" }) +
    $(if (-not $hasTerms) { "; WARNING no deny list yet: rerun with -TermsFrom <folder of student projects>" } else { "" }) +
    $(if ($syncReason -and $hasTerms) { "; WARNING a deny list already sits in a synchronized or shared location ($syncReason): move the guard to a local folder" } else { "" })
Write-Report $report 0
