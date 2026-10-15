#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of scripts\local\claude-switch.ps1's claude-ollama / claude-augure /
    claude-cloud functions: resolver-based default (R2, no hardcoded tag), the
    Ollama-reachability AND model-presence guards, claude-augure's AugureAI redirection,
    and the shared ANTHROPIC_API_KEY save/restore across all three (PR #61 review
    finding #1 - claude-cloud used to never bring it back; extended 2026-10-15 to prove
    the three-state chain restores the ORIGINAL key regardless of which two states run
    in between).

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

# Superset for Save-RealEnv/Restore-RealEnv around the WHOLE run, needed BEFORE the
# production script is even dot-sourced (Save-RealEnv is called first, to protect the
# real caller's environment from the moment this test starts). Also covers
# AUGUREAI_API_KEY, a fixture INPUT the test sets per case, never cleared between cases
# (Clear-SwitchEnv, defined below, must not wipe a credential the test itself just
# configured).
$RoutingVars = @(
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_API_KEY", "AUGUREAI_API_KEY"
)

function Clear-SwitchEnv {
    # Reads $script:RoutingVarNames from the DOT-SOURCED production script itself
    # (code-review finding, 2026-10-15) rather than a second, separately maintained
    # list here: a literal copy would silently stop covering a variable the script
    # starts managing later, reintroducing the exact cross-case leakage this
    # function exists to prevent (see $script:EnvSaved below). Dot-sourcing has no
    # scope boundary, so the production script's own $script:RoutingVarNames is
    # already visible here by the time any test case calls this function.
    Remove-Item ($script:RoutingVarNames | ForEach-Object { "Env:\$_" }) -ErrorAction SilentlyContinue
    # $script:EnvSaved/$script:SavedEnv are PowerShell-scope bookkeeping, not env
    # vars - clearing only Env:\* would leak one test case's save-state into the next
    # (measured: it did, failing the "ollama -> augure -> cloud" chain test below until
    # this reset was added). Each test case simulates a FRESH shell.
    $script:EnvSaved = $false
    $script:SavedEnv = $null
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

    # Resolve-PythonInterpreter would otherwise return a REAL full path to this
    # machine's own .venv-skills\python.exe when that venv exists on disk - and
    # `& $fullPath ...` invokes that path directly, bypassing a shadowed BARE-name
    # `python` function entirely (function/alias resolution only applies to bare
    # command names). Without this override the test would silently call the REAL
    # resolver against the REAL state file, exactly the machine-dependence R21
    # exists to rule out. Returning the bare string "python" here routes the call
    # through the shadow below instead.
    function Resolve-PythonInterpreter { param($RepoRoot) return "python" }

    # Simulates 'python <resolver> --resolve --role session --require-role': controlled by
    # $script:FakeResolverTag (empty/null => resolver failure, nonzero exit).
    function python {
        if ($script:FakeResolverTag) {
            $global:LASTEXITCODE = 0
            return $script:FakeResolverTag
        }
        $global:LASTEXITCODE = 1
        return ""
    }

    # --- 0. Regression: the FIRST call in a freshly dot-sourced shell must not crash
    # reading $script:EnvSaved before it has ever been set (Set-StrictMode would turn
    # that into a terminating error - this is the bug the explicit init line exists for).
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $threw = $false
    try { claude-cloud } catch { $threw = $true }
    Check "claude-cloud as the very first call does not throw under StrictMode" (-not $threw)

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

    # --- 6b. claude-augure refuses without AUGUREAI_API_KEY, touches nothing ---
    Clear-SwitchEnv
    Remove-Item Env:\AUGUREAI_API_KEY -ErrorAction SilentlyContinue
    $script:claudeCallCount = 0
    claude-augure
    Check "missing AUGUREAI_API_KEY blocks claude-augure" ($script:claudeCallCount -eq 0)
    Check "missing AUGUREAI_API_KEY sets no env vars"     (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

    # --- 6c. claude-augure: base url + key set, stale Ollama vars cleared, claude invoked ---
    Clear-SwitchEnv
    $env:AUGUREAI_API_KEY = "augure-secret-key"
    $script:claudeCallCount = 0
    claude-augure
    Check "augure sets its own base url"      ($env:ANTHROPIC_BASE_URL -eq "https://api.augureai.ca/v1")
    Check "augure sets ANTHROPIC_API_KEY from AUGUREAI_API_KEY" ($env:ANTHROPIC_API_KEY -eq "augure-secret-key")
    Check "augure invoked claude once"        ($script:claudeCallCount -eq 1)

    # Ollama's own vars must not survive a prior claude-ollama call once augure runs.
    Clear-SwitchEnv
    $script:FakeOllamaUp = $true
    $script:FakeInstalled = @("resolved-tag:test")
    claude-ollama -Model "resolved-tag:test"
    $script:claudeCallCount = 0
    claude-augure
    Check "augure clears a stale Ollama auth token"   (-not (Test-Path Env:\ANTHROPIC_AUTH_TOKEN))
    Check "augure clears a stale Ollama model"        (-not (Test-Path Env:\ANTHROPIC_MODEL))
    Check "augure clears a stale Ollama timeout"      (-not (Test-Path Env:\API_TIMEOUT_MS))
    Check "augure clears a stale offline-mode flag"   (-not (Test-Path Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC))

    # --- 6d. Three-state chain: cloud(real key) -> ollama -> augure -> cloud restores the
    # ORIGINAL key, not an intermediate one. This is the bug Save-OriginalApiKeyOnce exists
    # to prevent: an unconditional per-function save would have the second hop (augure)
    # overwrite the saved value with whatever was present at THAT point (nothing useful),
    # and claude-cloud would restore the wrong thing.
    Clear-SwitchEnv
    $env:ANTHROPIC_API_KEY = "sk-original-cloud-key"
    claude-ollama -Model "resolved-tag:test"
    claude-augure
    claude-cloud
    Check "ollama -> augure -> cloud restores the ORIGINAL key" ($env:ANTHROPIC_API_KEY -eq "sk-original-cloud-key")

    # Same chain, reversed order.
    Clear-SwitchEnv
    $env:ANTHROPIC_API_KEY = "sk-original-cloud-key-2"
    claude-augure
    claude-ollama -Model "resolved-tag:test"
    claude-cloud
    Check "augure -> ollama -> cloud restores the ORIGINAL key" ($env:ANTHROPIC_API_KEY -eq "sk-original-cloud-key-2")

    # --- 6d2. Code-review finding, 2026-10-15: claude-augure as the FIRST switch in a shell
    # must snapshot a pre-existing routing var BEFORE clearing it, not after. The old order
    # (clear stale Ollama vars, THEN Save-OriginalEnvOnce) destroyed the user's real value
    # before it was ever saved, so claude-cloud "restored" the deletion instead of the
    # original.
    Clear-SwitchEnv
    $env:ANTHROPIC_MODEL = "my-custom-model"
    claude-augure
    claude-cloud
    Check "augure-first preserves a pre-existing ANTHROPIC_MODEL for claude-cloud to restore" ($env:ANTHROPIC_MODEL -eq "my-custom-model")

    # --- 6e. M1: claude-cloud restores a pre-existing custom ANTHROPIC_BASE_URL (e.g. a
    # corporate gateway), not just the API key. Earlier revisions restored ONLY the key and
    # left every other variable blind-deleted.
    Clear-SwitchEnv
    $env:ANTHROPIC_BASE_URL = "https://corporate-gateway.example.com"
    claude-ollama -Model "resolved-tag:test"
    claude-cloud
    Check "cloud restores a pre-existing custom BASE_URL (M1)" ($env:ANTHROPIC_BASE_URL -eq "https://corporate-gateway.example.com")

    # --- 6f. M2: a bare tag (no ":tag") is normalized before comparison ---
    Clear-SwitchEnv
    $script:claudeCallCount = 0
    $script:FakeInstalled = @("qwen3.5:latest")
    claude-ollama -Model "qwen3.5"
    Check "bare tag matches an installed :latest entry (M2)" ($script:claudeCallCount -eq 1)
    Check "bare tag reaches ANTHROPIC_MODEL unmodified"      ($env:ANTHROPIC_MODEL -eq "qwen3.5")

    # --- 7. ANTHROPIC_API_KEY restore (review finding #1, the real bug) ---
    # Explicit fixture reset: test 6f (M2) overwrote $script:FakeInstalled with a list that
    # does not contain "resolved-tag:test", and relying on carryover from an earlier block
    # is exactly the kind of cross-case leakage already fixed once in this file (EnvSaved).
    Clear-SwitchEnv
    $script:FakeResolverTag = "resolved-tag:test"
    $script:FakeInstalled = @("resolved-tag:test")
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
    $script:EnvSaved = $false   # simulate a fresh shell that never called claude-ollama
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
