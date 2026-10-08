#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of scripts\local\claude-switch.ps1's claude-ollama / claude-cloud
    functions: env vars set and cleared correctly, and the Ollama-reachability
    guard actually stops the switch rather than launching Claude Code against a
    dead port.

.DESCRIPTION
    Dot-sources the real script, then shadows Test-NetConnection and claude with
    local functions so no real network call and no real Claude Code / Ollama
    process is ever started (R21: no machine-local dependency in the test).
    PowerShell resolves a function over a cmdlet or external executable of the
    same name for the rest of the session, which is what the shadowing relies on.

.NOTES
    Not part of the green-stamp gate (Python-only). Run manually, same family as
    scripts\test\verify-sync-writes.ps1.

.EXAMPLE
    .\scripts\local\Test\verify-claude-switch.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$ScriptUnderTest = Join-Path $RepoRoot "scripts\local\claude-switch.ps1"
$failures  = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Clear-SwitchEnv {
    Remove-Item Env:\ANTHROPIC_BASE_URL, Env:\ANTHROPIC_AUTH_TOKEN, Env:\ANTHROPIC_MODEL, `
        Env:\ANTHROPIC_SMALL_FAST_MODEL, Env:\API_TIMEOUT_MS, `
        Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, Env:\ANTHROPIC_API_KEY `
        -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=== claude-switch.ps1 ===" -ForegroundColor Cyan

Check "script exists" (Test-Path $ScriptUnderTest)
if (-not (Test-Path $ScriptUnderTest)) {
    Write-Host "Cannot continue without the script." -ForegroundColor Red
    exit 1
}

. $ScriptUnderTest

# --- shadow the two real dependencies, never invoked for real ---
$script:claudeCallCount = 0
function claude { $script:claudeCallCount++ }

function Test-NetConnection {
    param($ComputerName, $Port, $WarningAction, $InformationLevel)
    return $script:FakeOllamaUp
}

# --- 1. Ollama up: env vars set, claude invoked once, default model used ---
Clear-SwitchEnv
$script:claudeCallCount = 0
$script:FakeOllamaUp = $true
claude-ollama

Check "base url set"            ($env:ANTHROPIC_BASE_URL -eq "http://localhost:11434")
Check "auth token is 'ollama'"  ($env:ANTHROPIC_AUTH_TOKEN -eq "ollama")
Check "model defaults"          ($env:ANTHROPIC_MODEL -eq "qwen2.5-coder:7b")
Check "small-fast model mirrors main"  ($env:ANTHROPIC_SMALL_FAST_MODEL -eq $env:ANTHROPIC_MODEL)
Check "timeout set"              ($env:API_TIMEOUT_MS -eq "600000")
Check "offline mode set"         ($env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC -eq "1")
Check "claude invoked once"      ($script:claudeCallCount -eq 1)

# --- 2. -Model override actually reaches ANTHROPIC_MODEL, not just the default ---
Clear-SwitchEnv
$script:claudeCallCount = 0
$script:FakeOllamaUp = $true
claude-ollama -Model "qwen3.5:9b-gpu"
Check "explicit -Model overrides default" ($env:ANTHROPIC_MODEL -eq "qwen3.5:9b-gpu")

# --- 3. Ollama down: guard refuses, claude never invoked, no env vars set ---
Clear-SwitchEnv
$script:claudeCallCount = 0
$script:FakeOllamaUp = $false
claude-ollama
Check "unreachable Ollama blocks the switch" ($script:claudeCallCount -eq 0)
Check "unreachable Ollama sets no env vars"  (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

# --- 4. claude-cloud clears everything claude-ollama set, and still launches ---
$script:FakeOllamaUp = $true
$script:claudeCallCount = 0
claude-ollama
$script:claudeCallCount = 0
claude-cloud
Check "cloud clears base url"    (-not (Test-Path Env:\ANTHROPIC_BASE_URL))
Check "cloud clears auth token"  (-not (Test-Path Env:\ANTHROPIC_AUTH_TOKEN))
Check "cloud clears model"       (-not (Test-Path Env:\ANTHROPIC_MODEL))
Check "cloud clears small-fast model" (-not (Test-Path Env:\ANTHROPIC_SMALL_FAST_MODEL))
Check "cloud clears timeout"     (-not (Test-Path Env:\API_TIMEOUT_MS))
Check "cloud clears offline flag" (-not (Test-Path Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC))
Check "claude still invoked by claude-cloud" ($script:claudeCallCount -eq 1)

Clear-SwitchEnv

Write-Host ""
if ($failures -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
