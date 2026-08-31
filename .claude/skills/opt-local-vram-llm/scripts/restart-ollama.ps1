#Requires -Version 5.1
<#
.SYNOPSIS
    Restart the local Ollama daemon and free every GPU-resident model instance.

.DESCRIPTION
    The one correct way to restart Ollama on this machine. Use it before and after any
    change to an OLLAMA_* environment variable, since the daemon reads those once at
    start and never re-reads them.

    WHY THIS SCRIPT EXISTS, and the trap it removes:

        Stop-Process -Name "ollama*"

    looks complete and is not. Ollama runs the model in a CHILD process named
    llama-server.exe, whose name does not match that pattern, so the child survives its
    parent and keeps holding its slice of VRAM. Up to three orphaned instances were
    observed this way on 2026-08-14, and they produced a false measurement: a throughput
    comparison read as "q8_0 halves throughput" when what it actually measured was a card
    shared with two orphans. Any restart procedure must kill BOTH names, which is what
    Stop-OllamaProcesses below does, and must then verify against nvidia-smi that the VRAM
    actually came back rather than trust the kill.

    A restart is NOT enough on its own to change a setting: an environment variable set
    with [Environment]::SetEnvironmentVariable(..., 'User') is read by processes started
    afterwards, so the daemon must be stopped AFTER the variable is written, never before.

.EXAMPLE
    .\.claude\skills\opt-local-vram-llm\scripts\restart-ollama.ps1
    .\.claude\skills\opt-local-vram-llm\scripts\restart-ollama.ps1 -SkipStart      # stop only, leave the card idle
    .\.claude\skills\opt-local-vram-llm\scripts\restart-ollama.ps1 -TimeoutSeconds 60
#>
param(
    [switch]$SkipStart,
    [int]$TimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$text) { Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Ok([string]$text)   { Write-Host "  [OK]  $text" -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host "  [!!]  $text" -ForegroundColor Yellow }

# Both name patterns, and this is the whole point of the script: "ollama*" alone leaves
# the llama-server.exe child alive and GPU-resident. "llama-server*" does not match
# "ollama" either (it starts with an "o"), so neither pattern is redundant.
$processPatterns = @("ollama app", "ollama", "llama-server")

function Get-OllamaProcesses {
    $found = @()
    foreach ($pattern in $processPatterns) {
        $found += Get-Process -Name $pattern -ErrorAction SilentlyContinue
    }
    return $found
}

function Get-FreeVramMib {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return $null }
    $value = (& nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | Select-Object -First 1)
    if ($value -match '^\s*(\d+)\s*$') { return [int]$Matches[1] }
    return $null
}

function Stop-OllamaProcesses([int]$timeout) {
    # @() around every call: PowerShell unrolls a one-element array on return, and under
    # Set-StrictMode reading .Count on the resulting single Process object is a
    # terminating error - which would abort the restart precisely when exactly one
    # process is left, the case this loop exists to watch.
    $running = @(Get-OllamaProcesses)
    if ($running.Count -eq 0) {
        Write-Ok "nothing to stop (no ollama, ollama app, or llama-server process)"
        return
    }
    foreach ($proc in $running) {
        Write-Host "  stopping $($proc.ProcessName) (pid $($proc.Id))"
    }
    $running | Stop-Process -Force -ErrorAction SilentlyContinue

    # Verify by effect, not by the return of Stop-Process: a process can linger while the
    # driver releases its context, and reporting a restart that did not happen is the
    # failure mode this whole script exists to prevent.
    $deadline = (Get-Date).AddSeconds($timeout)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-OllamaProcesses).Count -eq 0) {
            Write-Ok "every ollama and llama-server process is gone"
            return
        }
        Start-Sleep -Milliseconds 250
    }
    $left = @(Get-OllamaProcesses) | ForEach-Object { "$($_.ProcessName)($($_.Id))" }
    throw "still running after $timeout s: $($left -join ', '). Kill them by hand before measuring anything."
}

Write-Step "GPU before"
$before = Get-FreeVramMib
if ($null -eq $before) { Write-Warn "nvidia-smi not available; VRAM cannot be verified" }
else { Write-Host "  free VRAM: $before MiB" }

Write-Step "Stopping Ollama (daemon, tray app, and the llama-server children)"
Stop-OllamaProcesses $TimeoutSeconds

$after = Get-FreeVramMib
if ($null -ne $after) {
    Write-Host "  free VRAM after stop: $after MiB"
    if ($null -ne $before -and $after -lt $before) {
        Write-Warn "free VRAM went DOWN after the stop; something else is loading the card"
    }
}

if ($SkipStart) {
    Write-Host ""
    Write-Host "Stopped. Not restarting (-SkipStart)." -ForegroundColor Green
    exit 0
}

Write-Step "Starting Ollama"

# A child process inherits THIS process's environment block, which was captured when this
# PowerShell started and therefore predates any [Environment]::SetEnvironmentVariable(...,
# 'User') the caller made a moment ago. Re-read the User scope into this process so the
# daemon starts on the values the caller actually wrote. Measured 2026-08-28: without these
# six lines the registry held OLLAMA_KV_CACHE_TYPE=q8_0 while the daemon's own "server
# config" line reported it empty, so a sweep would have attributed its numbers to a setting
# that was never active - the same class of false measurement as the orphaned llama-server
# processes this script already guards against.
foreach ($name in @("OLLAMA_KV_CACHE_TYPE", "OLLAMA_FLASH_ATTENTION", "OLLAMA_KEEP_ALIVE",
                    "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS")) {
    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if ([string]::IsNullOrWhiteSpace($userValue)) {
        if (Test-Path ("Env:" + $name)) { Remove-Item -Path ("Env:" + $name) }
    } else {
        Set-Item -Path ("Env:" + $name) -Value $userValue
    }
}
$app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
if (Test-Path $app) {
    # The tray app starts the daemon itself; starting "ollama serve" as well would fight
    # it for port 11434.
    Start-Process -FilePath $app | Out-Null
    Write-Ok "launched $app"
} else {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    Write-Ok "launched 'ollama serve'"
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$up = $false
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $up = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $up) { throw "the daemon did not answer http://127.0.0.1:11434/api/version within $TimeoutSeconds s" }

$version = (Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -UseBasicParsing -TimeoutSec 5).Content
Write-Ok "daemon answering: $version"

Write-Host ""
Write-Host "Restarted. The daemon has re-read the OLLAMA_* environment variables." -ForegroundColor Green
Write-Host "Active in this shell:"
foreach ($name in @("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS")) {
    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if ([string]::IsNullOrWhiteSpace($userValue)) { $userValue = "(unset, daemon default)" }
    Write-Host ("  {0,-26} {1}" -f $name, $userValue)
}
Write-Host ""

# Explicit, because a caller is entitled to trust this code: falling off the end leaves
# whatever the last command set, which is exactly the defect fixed in setup.ps1 this same
# day (a wrapper that reported success while the thing it called had failed).
exit 0
