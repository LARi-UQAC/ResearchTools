<#
.SYNOPSIS
  Publish a gated kit as aider-kit.zip, with a manifest a recipient can check.

.DESCRIPTION
  This exists because of two measured failures, one at each end of the wire.

  On the BUILDING machine, 2026-09-05: Compress-Archive was pointed straight at
  the published path, the destination was locked, and it left a 172267-byte
  archive that opened and listed files and was simply short. So this script
  stages to a temporary name, opens the staged archive, checks its entry count
  against the build's own declaration, and moves it into place only then.

  On the RECEIVING machine that fix does nothing at all, which is the second
  failure: a truncated download opens, lists files, and is missing some, and the
  recipient can neither detect it nor diagnose it. So this also writes
  <zip>.manifest BESIDE the archive - never inside it, because a manifest that
  lists itself changes the count it declares and every later reader then has to
  reason about that - carrying the byte size, the SHA-256 and the declared paths.

  What that manifest is NOT is a security control. Anyone who can alter the zip
  can alter the manifest next to it. It detects truncation, a partial extraction
  and a missing file. That is the whole claim.

.PARAMETER Kit
  The assembled kit directory. Its declaration is read from <Kit>.manifest,
  written by build_kit.py and added to by the three steps after it.

.PARAMETER Destination
  Where the published archive goes. Defaults to the kit folder's aider-kit.zip.

.PARAMETER Force
  Publish even though verify-kit-install.ps1 was not run against this tree in
  this shell. The gate is the reason the kit installs at all, so skipping it is
  a deliberate act and is named in the output rather than assumed.

.EXAMPLE
  .\verify-kit-install.ps1 -Kit C:\Temp\pub-kit
  .\publish_kit.ps1 -Kit C:\Temp\pub-kit
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Kit,
    [string]$Destination = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Kit)) {
    Write-Host "REFUSED: -Kit $Kit does not exist." -ForegroundColor Red
    exit 2
}
$manifestIn = $Kit + ".declared"
if (-not (Test-Path -LiteralPath $manifestIn)) {
    # Never a fallback to walking the tree. The declaration is the only thing
    # that can tell a leaked file from a shipped one (R8).
    Write-Host "REFUSED: no declaration at $manifestIn. Re-run the four build steps." -ForegroundColor Red
    exit 2
}
if ($Destination -eq "") {
    $Destination = Join-Path (Join-Path $HOME ".config\aider") "aider-kit.zip"
}

$declared = @(Get-Content -LiteralPath $manifestIn -Encoding UTF8 |
              ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
Write-Host ("declared: {0} files" -f $declared.Count)

# --- stage, then check, then move -------------------------------------------
$staged = Join-Path $env:TEMP ("aider-kit-staging-" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".zip")
$glob = $Kit.TrimEnd([char]92) + [char]92 + [char]42
Compress-Archive -Path $glob -DestinationPath $staged -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($staged)
try {
    # A directory entry carries an empty Name. Counting entries rather than
    # files is how a 51-file kit reads as 53 and the difference means nothing.
    $entries = @($zip.Entries | Where-Object { $_.Name -ne "" } | ForEach-Object { $_.FullName })
} finally {
    $zip.Dispose()
}

$leaked  = @($entries  | Where-Object { $declared -notcontains $_ })
$missing = @($declared | Where-Object { $entries  -notcontains $_ })
if ($leaked.Count -ne 0 -or $missing.Count -ne 0) {
    Write-Host "REFUSED: the staged archive does not hold what the build declared." -ForegroundColor Red
    if ($leaked.Count  -gt 0) { Write-Host ("  in the zip, never declared: " + ($leaked  -join ", ")) -ForegroundColor Red }
    if ($missing.Count -gt 0) { Write-Host ("  declared, not in the zip: "   + ($missing -join ", ")) -ForegroundColor Red }
    Write-Host "The published copy was not touched. Staged archive left at $staged" -ForegroundColor Red
    exit 1
}

if (-not $Force) {
    Write-Host "NOTE: run verify-kit-install.ps1 against this tree first if you have not." -ForegroundColor Yellow
}

Move-Item -LiteralPath $staged -Destination $Destination -Force
$size = (Get-Item -LiteralPath $Destination).Length
$sha  = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLower()

# --- the manifest the RECIPIENT reads ---------------------------------------
$name = Split-Path -Leaf $Destination
$lines = @(
    "# Manifest for $name",
    "#",
    "# What this is for: checking that the archive you downloaded is whole and",
    "# that it extracted completely. It detects a truncated download, a partial",
    "# extraction and a missing file.",
    "#",
    "# What it is NOT: a security control. Anyone able to alter the archive can",
    "# alter this file beside it. It proves nothing about where the archive came",
    "# from and nothing about whether its contents are safe.",
    "#",
    "# Before extracting, from the folder holding both files:",
    "#   Get-FileHash .\$name -Algorithm SHA256",
    "#   (Get-Item .\$name).Length",
    "# and compare with the two values below.",
    "#",
    "# After extracting, from the folder you extracted INTO:",
    "#   `$d = Get-Content <path to this file> |",
    "#        Where-Object { `$_ -notmatch '^#|^size |^sha256 ' } | Where-Object { `$_ -ne '' }",
    "#   `$d | Where-Object { -not (Test-Path -LiteralPath `$_) }",
    "# Anything printed is a file the archive declares and your disk does not have.",
    "#",
    "size $size",
    "sha256 $sha",
    ""
) + $declared
$out = $Destination + ".manifest"
[System.IO.File]::WriteAllText($out, ($lines -join [Environment]::NewLine) + [Environment]::NewLine,
                               (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host ("PUBLISHED {0}" -f $Destination) -ForegroundColor Green
Write-Host ("  {0} bytes, {1} files" -f $size, $entries.Count)
Write-Host ("  sha256 {0}" -f $sha)
Write-Host ("  manifest: {0}" -f $out)
