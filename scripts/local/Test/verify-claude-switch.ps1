#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of scripts\local\claude-switch.ps1's claude-ollama / claude-cloud
    functions: resolver-based default (R2, no hardcoded tag), the Ollama-reachability
    AND model-presence guards, and the ANTHROPIC_API_KEY save/restore (PR #61 review
    finding #1 - claude-cloud used to never bring it back).

.DESCRIPTION
    Dot-sources the real script, then shadows Test-NetConnection, ollama, python and
    claude with local functions so no real network call, no real Ollama daemon call,
    no real resolver invocation and no real Claude Code process is ever started (R21:
    no machine-local dependency in the test - this must pass identically whether or
    not THIS machine currently has a 'session' role adopted).

    PR #61 review (finding #2 / L3): the PREVIOUS version of this test cleared the
    CALLER's real ANTHROPIC_* env vars at the end via Clear-SwitchEnv with no restore,
    so running this file in an interactive shell that had a real ANTHROPIC_API_KEY set
    would silently delete it. This version snapshots the real environment before
    touching anything and restores it in a finally block, whatever happens.

.NOTES
    Not part of the green-stamp gate (Python-only). Run manually, same family as
    scripts\test\verify-sync-writes.ps1. The "resolver script path not found at all"
    branch of Resolve-SessionModelTag is NOT exercised here (it would need faking
    $PSScriptRoot itself) - only the "found but refuses/fails" branch is, via the
    shadowed `python`. Stated rather than silently assumed covered (R15).

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

$RoutingVars = @(
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_API_KEY"
)

function Clear-SwitchEnv {
    Remove-Item ($RoutingVars | ForEach-Object { "Env:\$_" }) -ErrorAction SilentlyContinue
}

function Save-RealEnv {
    $snapshot = @{}
    foreach ($name in $RoutingVars) { $snapshot[$name] = [Environment]::GetEnvironmentVariable($name) }
    return $snapshot
}

function Restore-RealEnv([hashtable]$snapshot) {
    foreach ($name in $RoutingVars) {
        if ($null -ne $snapshot[$name]) { Set-Item "Env:\$name" $snapshot[$name] }
        else { Remove-Item "Env:\$name" -ErrorAction SilentlyContinue }
    }
}

Write-Host ""
Write-Host "=== claude-switch.ps1 ===" -ForegroundColor Cyan

Check "script exists" (Test-Path $ScriptUnderTest)
if (-not (Test-Path $ScriptUnderTest)) {
    Write-Host "Cannot continue without the script." -ForegroundColor Red
    exit 1
}

$realEnv = Save-RealEnv
try {
    . $ScriptUnderTest

    # --- shadow every real dependency, never invoked for real ---
    $script:claudeCallCount = 0
    function claude { $script:claudeCallCount++ }

    function Test-NetConnection {
        param($ComputerName, $Port, $WarningAction, $InformationLevel)
        return $script:FakeOllamaUp
    }

    # Simulates 'ollama list': header row + one row per name in $script:FakeInstalled.
    function ollama {
        param([string]$Verb)
        $global:LASTEXITCODE = 0
        if ($Verb -ne "list") { return "" }
        $rows = @("NAME ID SIZE MODIFIED")
        foreach ($tag in $script:FakeInstalled) { $rows += "$tag deadbeef 1.0GB 1 day ago" }
        return ($rows -join "`n")
    }

    # Simulates 'python <resolver> --resolve --role session': controlled by
    # $script:FakeResolverTag (empty/null => resolver failure, nonzero exit).
    function python {
        if ($script:FakeResolverTag) {
            $global:LASTEXITCODE = 0
            return $script:FakeResolverTag
        }
        $global:LASTEXITCODE = 1
        return ""
    }

    # --- 1. Default resolution: no -Model, resolver succeeds, model installed ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeOllamaUp = $true
    $script:FakeResolverTag = "resolved-tag:test"
    $script:FakeInstalled = @("resolved-tag:test")
    claude-ollama

    Check "resolver-supplied model reaches ANTHROPIC_MODEL" ($env:ANTHROPIC_MODEL -eq "resolved-tag:test")
    Check "base url set"            ($env:ANTHROPIC_BASE_URL -eq "http://127.0.0.1:11434")
    Check "auth token is 'ollama'"  ($env:ANTHROPIC_AUTH_TOKEN -eq "ollama")
    Check "small-fast model mirrors main"  ($env:ANTHROPIC_SMALL_FAST_MODEL -eq $env:ANTHROPIC_MODEL)
    Check "timeout set"              ($env:API_TIMEOUT_MS -eq "600000")
    Check "offline mode set"         ($env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC -eq "1")
    Check "claude invoked once"      ($script:claudeCallCount -eq 1)

    # --- 2. Explicit -Model overrides the resolver ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeInstalled = @("resolved-tag:test", "qwen3.5:9b-gpu")
    claude-ollama -Model "qwen3.5:9b-gpu"
    Check "explicit -Model overrides resolver" ($env:ANTHROPIC_MODEL -eq "qwen3.5:9b-gpu")

    # --- 3. Ollama unreachable: guard refuses, claude never invoked, no env vars set ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeOllamaUp = $false
    claude-ollama -Model "resolved-tag:test"
    Check "unreachable Ollama blocks the switch" ($script:claudeCallCount -eq 0)
    Check "unreachable Ollama sets no env vars"  (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

    # --- 4. Ollama reachable but the requested model is NOT installed (finding #5) ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeOllamaUp = $true
    $script:FakeInstalled = @("some-other-model:latest")
    claude-ollama -Model "resolved-tag:test"
    Check "missing model blocks the switch"      ($script:claudeCallCount -eq 0)
    Check "missing model sets no env vars"       (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

    # --- 5. Resolver failure with no -Model: refused, claude never invoked ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeOllamaUp = $true
    $script:FakeResolverTag = $null
    claude-ollama
    Check "resolver failure blocks the switch (no -Model given)" ($script:claudeCallCount -eq 0)

    # --- 6. claude-cloud clears routing vars, still launches claude ---
    $script:FakeResolverTag = "resolved-tag:test"
    $script:FakeInstalled = @("resolved-tag:test")
    $script:FakeOllamaUp = $true
    $script:claudeCallCount = 0
    claude-ollama
    $script:claudeCallCount = 0
    claude-cloud
    Check "cloud clears base url"    (-not (Test-Path Env:\ANTHROPIC_BASE_URL))
    Check "cloud clears model"       (-not (Test-Path Env:\ANTHROPIC_MODEL))
    Check "claude still invoked by claude-cloud" ($script:claudeCallCount -eq 1)

    # --- 7. ANTHROPIC_API_KEY restore (review finding #1, the real bug) ---
    Clear-SwitchEnv
    $env:ANTHROPIC_API_KEY = "sk-real-cloud-key"
    claude-ollama
    Check "claude-ollama removes the cloud key while local" (-not (Test-Path Env:\ANTHROPIC_API_KEY))
    claude-cloud
    Check "claude-cloud restores the ORIGINAL cloud key" ($env:ANTHROPIC_API_KEY -eq "sk-real-cloud-key")

    # --- 8. API key restore, negative control: no key existed to begin with ---
    Clear-SwitchEnv
    claude-ollama
    claude-cloud
    Check "no key before -> no key fabricated after" (-not (Test-Path Env:\ANTHROPIC_API_KEY))

    # --- 9. claude-cloud with NO prior claude-ollama this run: leaves an existing key alone ---
    Clear-SwitchEnv
    $script:ApiKeySaved = $false   # simulate a fresh shell that never called claude-ollama
    $env:ANTHROPIC_API_KEY = "sk-untouched"
    claude-cloud
    Check "claude-cloud never touches a key it didn't save" ($env:ANTHROPIC_API_KEY -eq "sk-untouched")

    Clear-SwitchEnv
} finally {
    Restore-RealEnv $realEnv
}

Write-Host ""
if ($failures -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
