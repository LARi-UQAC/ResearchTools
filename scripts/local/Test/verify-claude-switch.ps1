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
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_API_KEY", "AUGUREAI_API_KEY",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    # claude-augure never reads or writes these from the session: the keys come from USER scope
    # (Issue #112). They are snapshotted, cleared and restored so a shell that has them set
    # does not make the checks depend on the machine (R21).
    "AUGURE_MCP_KEY", "LITELLM_MASTER_KEY"
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
# Clear the augure-dependent variables AFTER the snapshot, so the run starts from a known
# state whatever this shell inherited. Restore-RealEnv in the finally block puts the
# caller's values back exactly, absent ones included.
foreach ($name in @("AUGURE_MCP_KEY", "LITELLM_MASTER_KEY", "AUGUREAI_API_KEY")) {
    Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
}
try {
    . $ScriptUnderTest

    # The AugureAI section below shadows these two; keep the real code for the liveness and
    # settings checks of Issue #75 (the proxy address and the 2xx liveness answer).
    $realTestAugureProxy     = ${function:Test-AugureProxy}
    $realReadAugureDataFile  = ${function:Read-AugureDataFile}

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
    # The window question (`--window --role session`) is answered from $script:FakeWindow
    # (null => the resolver refuses, exit 2), so no real state file is ever read (R21).
    $script:FakeWindow = $null
    function python {
        if ($args -contains "--window") {
            if ($script:FakeWindow) { $global:LASTEXITCODE = 0; return "$($script:FakeWindow)" }
            $global:LASTEXITCODE = 2
            return ""
        }
        if ($script:FakeResolverTag) {
            $global:LASTEXITCODE = 0
            return $script:FakeResolverTag
        }
        $global:LASTEXITCODE = 1
        return ""
    }

    # --- AugureAI route (Issue #112): every effect shadowed, so no registry, network or key is read (R21) ---
    $script:AugureUser = @{}
    $script:AugureUserReads = @()
    $script:AugureProxyUp = $true
    $script:AugureChoice = "1"
    $script:AugureMenuAsked = 0
    $script:AugurePyExit = 0
    $script:AugurePyStdout = ""
    $script:AugurePyCall = $null

    function Read-AugureUserEnv {
        param([Parameter(Mandatory)][string]$Name)
        $script:AugureUserReads += $Name
        if ($script:AugureUser.ContainsKey($Name)) { return $script:AugureUser[$Name] }
        return $null
    }
    function Read-AugureChoice {
        param([Parameter(Mandatory)][string]$Prompt)
        $script:AugureMenuAsked++
        return $script:AugureChoice
    }
    function Test-AugureProxy {
        param([Parameter(Mandatory)][string]$Url, [Parameter(Mandatory)][int]$TimeoutSec)
        return $script:AugureProxyUp
    }
    function Invoke-AugureModelList {
        param([Parameter(Mandatory)][string]$Python, [Parameter(Mandatory)][string[]]$Arguments,
              [Parameter(Mandatory)][hashtable]$Environment, [Parameter(Mandatory)][int]$TimeoutMs)
        $script:AugurePyCall = @{ Python = $Python; Arguments = @($Arguments); Environment = $Environment }
        return @{ ExitCode = $script:AugurePyExit; Stdout = $script:AugurePyStdout; Stderr = $script:AugurePyStderr; TimedOut = $script:AugurePyTimedOut }
    }
    # Fictitious listing: rosedale-1 and ossington-5 are the two ids of the live account (2026-11-27);
    # rosedale-2 is a fictitious second selectable id used only for the model menu.
    function New-AugureReport {
        param([object[]]$Selectable = @(), [object[]]$Refused = @())
        $report = @{ profile = "dev"; selectable = @($Selectable); refused = @($Refused) }
        return ($report | ConvertTo-Json -Depth 5 -Compress)
    }
    function Get-AugurePyField {
        param([Parameter(Mandatory)][string]$Name)
        if ($script:AugurePyCall) { return $script:AugurePyCall[$Name] }
        return $null
    }
    function Set-AugureFixture {
        $script:AugureUser = @{ "AUGUREAI_API_KEY" = "user-api-key"; "AUGURE_MCP_KEY" = "user-mcp-key"; "LITELLM_MASTER_KEY" = "user-master-key" }
        $script:AugureUserReads = @()
        $script:AugureProxyUp = $true
        $script:AugureChoice = "1"
        $script:AugureMenuAsked = 0
        $script:AugurePyExit = 0
        $script:AugurePyStderr = ""
        $script:AugurePyTimedOut = $false
        $script:AugurePyCall = $null
        $script:AugurePyStdout = New-AugureReport -Selectable @(@{ id = "rosedale-1"; context_window = 1048576 }) -Refused @(@{ id = "ossington-5"; reason = "context window 262144 is below the required 1048576 (augure-models.json)" })
    }
    Set-AugureFixture

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

    # --- 6b. claude-augure refuses without the User-scope AUGUREAI_API_KEY, touches nothing ---
    Clear-SwitchEnv
    Set-AugureFixture
    $script:AugureUser.Remove("AUGUREAI_API_KEY")
    $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "missing User AUGUREAI_API_KEY blocks claude-augure" ($script:claudeCallCount -eq 0)
    Check "missing User AUGUREAI_API_KEY sets no env vars"     (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

    # --- 6c. claude-augure: proxy + master key, ANTHROPIC_API_KEY removed, claude invoked ---
    Clear-SwitchEnv
    Set-AugureFixture
    $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "augure sets the proxy base url"       ($env:ANTHROPIC_BASE_URL -eq "http://127.0.0.1:4000")
    Check "augure removes ANTHROPIC_API_KEY"     (-not (Test-Path Env:\ANTHROPIC_API_KEY))
    Check "augure auth token is the master key"  ($env:ANTHROPIC_AUTH_TOKEN -eq "user-master-key")
    Check "augure invoked claude once"           ($script:claudeCallCount -eq 1)

    # Ollama's own vars must not survive a prior claude-ollama call once augure runs.
    Clear-SwitchEnv
    $script:FakeOllamaUp = $true
    $script:FakeInstalled = @("resolved-tag:test")
    claude-ollama -Model "resolved-tag:test"
    Set-AugureFixture
    $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "augure replaces a stale Ollama auth token" ($env:ANTHROPIC_AUTH_TOKEN -eq "user-master-key")
    Check "augure replaces a stale Ollama model"      ($env:ANTHROPIC_MODEL -eq "augure-dev/rosedale-1")
    Check "augure clears a stale Ollama timeout"      (-not (Test-Path Env:\API_TIMEOUT_MS))
    Check "augure clears a stale offline-mode flag"   (-not (Test-Path Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC))

    # --- 6d. Three-state chain: cloud(real key) -> ollama -> augure -> cloud restores the
    # ORIGINAL key, not an intermediate one. This is the bug Save-OriginalApiKeyOnce exists
    # to prevent: an unconditional per-function save would have the second hop (augure)
    # overwrite the saved value with whatever was present at THAT point (nothing useful),
    # and claude-cloud would restore the wrong thing.
    Clear-SwitchEnv
    Set-AugureFixture
    $env:ANTHROPIC_API_KEY = "sk-original-cloud-key"
    claude-ollama -Model "resolved-tag:test"
    claude-augure
    claude-cloud
    Check "ollama -> augure -> cloud restores the ORIGINAL key" ($env:ANTHROPIC_API_KEY -eq "sk-original-cloud-key")

    # Same chain, reversed order.
    Clear-SwitchEnv
    Set-AugureFixture
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
    Set-AugureFixture
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

    # --- 6g. The context window (local coding contract plan 4). Claude Code assumes 200K
    # for a model ID it does not recognise, so claude-ollama tells it the window of the
    # session role when, and only when, that window is known for the tag being routed to.
    $script:FakeOllamaUp = $true
    $script:FakeResolverTag = "resolved-tag:test"
    $script:FakeInstalled = @("resolved-tag:test", "qwen3.5:9b-gpu")
    $script:FakeWindow = 262144
    Clear-SwitchEnv
    claude-ollama
    Check "window of the session role reaches CLAUDE_CODE_MAX_CONTEXT_TOKENS" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "262144")

    Clear-SwitchEnv
    claude-ollama -Model "resolved-tag:test"
    Check "explicit -Model equal to the session tag still gets the window" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "262144")

    Clear-SwitchEnv
    $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "999"
    $said = & { claude-ollama -Model "qwen3.5:9b-gpu" } *>&1 | Out-String
    Check "a tag that is not the session tag leaves the variable unset" (-not (Test-Path Env:\CLAUDE_CODE_MAX_CONTEXT_TOKENS))
    Check "and says Claude Code will assume 200K" ($said -match "200K")

    Clear-SwitchEnv
    $script:FakeWindow = $null
    $said = & { claude-ollama } *>&1 | Out-String
    Check "an unknown window leaves the variable unset" (-not (Test-Path Env:\CLAUDE_CODE_MAX_CONTEXT_TOKENS))
    Check "an unknown window is stated, not silent" ($said -match "200K")
    $script:FakeWindow = 262144

    Clear-SwitchEnv
    $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "111"
    claude-ollama
    claude-cloud
    Check "claude-cloud restores a pre-existing window variable" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "111")

    # Code review 2026-10-17: a bare tag that Test-OllamaHasModel accepted (normalised to
    # :latest) was compared raw with the session tag, so the window was left unset and the
    # advice printed was wrong.
    Clear-SwitchEnv
    $script:FakeResolverTag = "resolved-tag:latest"
    $script:FakeInstalled = @("resolved-tag:latest")
    claude-ollama -Model "resolved-tag"
    Check "a bare tag equal to the session tag after normalising still gets the window" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "262144")
    $script:FakeResolverTag = "resolved-tag:test"
    $script:FakeInstalled = @("resolved-tag:test", "qwen3.5:9b-gpu")

    Clear-SwitchEnv
    claude-ollama
    Set-AugureFixture
    $null = & { claude-augure -Profile dev } *>&1
    Check "claude-augure sets the window from the model's context_window" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "1048576")

    Clear-SwitchEnv
    $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "222"
    claude-ollama
    Set-AugureFixture
    claude-augure
    claude-cloud
    Check "ollama -> augure -> cloud restores the ORIGINAL window variable" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "222")

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

    # --- 10. claude-augure, Issue #112: profile, keys, proxy, model and routing variables ---
    $productionText = Get-Content -Raw -Encoding UTF8 $ScriptUnderTest
    Check "the hard-coded AugureBaseUrl is gone from the script" (-not ($productionText -match 'AugureBaseUrl'))
    Check "no window literal in the script (the window comes from augure-models.json)" (-not ($productionText -match '1048576'))
    Check "comment says separating the keys is one line of augure-profiles.json" ($productionText -match 'one line of augure-profiles\.json')

    # 10a. profile menu when -Profile is absent; answer 2 selects chat
    Clear-SwitchEnv; Set-AugureFixture; $script:AugureChoice = "2"; $script:claudeCallCount = 0
    $null = & { claude-augure } *>&1
    Check "profile menu asked once when -Profile is absent" ($script:AugureMenuAsked -eq 1)
    Check "menu answer 2 selects the chat profile" (@(Get-AugurePyField 'Arguments') -contains "chat")
    Check "the switch starts claude once with the chosen profile" ($script:claudeCallCount -eq 1)

    # 10b. unknown profile refused, nothing read
    Clear-SwitchEnv; Set-AugureFixture; $script:claudeCallCount = 0
    $said = & { claude-augure -Profile nope } *>&1 | Out-String
    Check "unknown -Profile refused, claude not started" ($script:claudeCallCount -eq 0)
    Check "unknown -Profile names the profile" ($said -match "nope")
    Check "unknown -Profile reads no key" ($script:AugureUserReads.Count -eq 0)

    # 10c. missing and empty MCP key refused, naming the variable
    Clear-SwitchEnv; Set-AugureFixture; $script:AugureUser.Remove("AUGURE_MCP_KEY"); $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev } *>&1 | Out-String
    Check "missing MCP key refused, claude not started" ($script:claudeCallCount -eq 0)
    Check "missing MCP key named in the refusal" ($said -match "AUGURE_MCP_KEY")
    Check "missing MCP key: the model listing never runs" ($null -eq $script:AugurePyCall)

    Clear-SwitchEnv; Set-AugureFixture; $script:AugureUser["AUGURE_MCP_KEY"] = ""; $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev } *>&1 | Out-String
    Check "empty MCP key refused, claude not started" ($script:claudeCallCount -eq 0)
    Check "empty MCP key named in the refusal" ($said -match "AUGURE_MCP_KEY")

    # 10d. proxy down refused, naming the autostart launcher
    Clear-SwitchEnv; Set-AugureFixture; $script:AugureProxyUp = $false; $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev } *>&1 | Out-String
    Check "proxy down refused, claude not started" ($script:claudeCallCount -eq 0)
    Check "proxy down names litellm-autostart.ps1" ($said -match "litellm-autostart\.ps1")
    Check "proxy down: no model listing" ($null -eq $script:AugurePyCall)

    # 10e. listing exits 2 with an empty selectable list: refused with every reason
    Clear-SwitchEnv; Set-AugureFixture; $script:AugurePyExit = 2
    $script:AugurePyStdout = New-AugureReport -Selectable @() -Refused @(@{ id = "ossington-5"; reason = "context window 262144 is below the required 1048576" })
    $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev } *>&1 | Out-String
    Check "empty listing refused, claude not started" ($script:claudeCallCount -eq 0)
    Check "empty listing prints the refused reason" ($said -match "262144 is below")

    # 10f. -Model not selectable refused with the window reason
    Clear-SwitchEnv; Set-AugureFixture; $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev -Model "ossington-5" } *>&1 | Out-String
    Check "-Model refused by window stops the switch" ($script:claudeCallCount -eq 0)
    Check "-Model refusal states the window reason" ($said -match "262144 is below")
    Check "-Model refusal sets no variable" (-not (Test-Path Env:\ANTHROPIC_BASE_URL))

    # 10g. one selectable model: used without a question, and printed
    Clear-SwitchEnv; Set-AugureFixture; $script:claudeCallCount = 0
    $said = & { claude-augure -Profile dev } *>&1 | Out-String
    Check "one selectable model asks no question" ($script:AugureMenuAsked -eq 0)
    Check "one selectable model is printed" ($said -match "rosedale-1")
    Check "one selectable model starts claude" ($script:claudeCallCount -eq 1)

    # 10h. final routing variables
    Check "base url is the proxy on 127.0.0.1:4000" ($env:ANTHROPIC_BASE_URL -eq "http://127.0.0.1:4000")
    Check "ANTHROPIC_MODEL is augure-dev/rosedale-1" ($env:ANTHROPIC_MODEL -eq "augure-dev/rosedale-1")
    Check "ANTHROPIC_SMALL_FAST_MODEL is augure-dev/rosedale-1" ($env:ANTHROPIC_SMALL_FAST_MODEL -eq "augure-dev/rosedale-1")
    Check "CLAUDE_CODE_MAX_CONTEXT_TOKENS is the model window 1048576" ($env:CLAUDE_CODE_MAX_CONTEXT_TOKENS -eq "1048576")
    Check "ANTHROPIC_API_KEY removed" (-not (Test-Path Env:\ANTHROPIC_API_KEY))
    Check "ANTHROPIC_AUTH_TOKEN is the master key" ($env:ANTHROPIC_AUTH_TOKEN -eq "user-master-key")

    # 10i. every refusal leaves every routing variable as it was
    Clear-SwitchEnv
    $env:ANTHROPIC_BASE_URL = "https://keep.example.test"
    $env:ANTHROPIC_API_KEY = "sk-keep"
    $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "77"
    $before = Save-RealEnv
    $keptAll = $true
    $refusals = @(
        { Set-AugureFixture; $script:AugureUser.Remove("AUGURE_MCP_KEY"); claude-augure -Profile dev },
        { Set-AugureFixture; $script:AugureProxyUp = $false; claude-augure -Profile dev },
        { Set-AugureFixture; $script:AugurePyExit = 1; claude-augure -Profile dev },
        { Set-AugureFixture; claude-augure -Profile dev -Model "ossington-5" },
        { Set-AugureFixture; claude-augure -Profile nope },
        { Set-AugureFixture; $script:AugureChoice = "9"; claude-augure }
    )
    foreach ($refusal in $refusals) {
        $null = & $refusal *>&1
        $after = Save-RealEnv
        foreach ($name in $RoutingVars) { if ($after[$name] -ne $before[$name]) { $keptAll = $false } }
    }
    Check "every refusal leaves every routing variable unchanged" $keptAll

    # 10j. the User-scope value is read; a stale process copy never stands in for it
    Clear-SwitchEnv; Set-AugureFixture
    $env:AUGUREAI_API_KEY = "stale-process-copy"
    $script:AugureUser["AUGUREAI_API_KEY"] = "fresh-user-value"; $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "AUGUREAI_API_KEY is read at User scope" ($script:AugureUserReads -contains "AUGUREAI_API_KEY")
    Check "a User value lets the switch proceed despite a stale process copy" ($script:claudeCallCount -eq 1)
    Set-AugureFixture
    $env:AUGUREAI_API_KEY = "stale-process-copy"
    $script:AugureUser.Remove("AUGUREAI_API_KEY"); $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "a process copy is never used in place of an absent User value" ($script:claudeCallCount -eq 0)
    Remove-Item Env:\AUGUREAI_API_KEY -ErrorAction SilentlyContinue

    # 10k. out-of-range and non-numeric menu answers refused, never a default
    Clear-SwitchEnv; Set-AugureFixture; $script:AugureChoice = "9"; $script:claudeCallCount = 0
    $said = & { claude-augure } *>&1 | Out-String
    Check "profile answer out of range refused, claude not started" ($script:claudeCallCount -eq 0 -and $null -eq $script:AugurePyCall)
    Check "out-of-range profile answer is stated" ($said -match "between 1 and 2")
    Clear-SwitchEnv; Set-AugureFixture; $script:AugureChoice = "x"; $script:claudeCallCount = 0
    $said = & { claude-augure } *>&1 | Out-String
    Check "non-numeric profile answer refused" ($script:claudeCallCount -eq 0 -and $said -match "between 1 and 2")

    # 10l. several models: a menu, out-of-range refused, in-range chosen
    Clear-SwitchEnv; Set-AugureFixture
    $script:AugurePyStdout = New-AugureReport -Selectable @(@{ id = "rosedale-1"; context_window = 1048576 }, @{ id = "rosedale-2"; context_window = 1048576 })
    $script:AugureChoice = "5"; $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "model answer out of range refused, nothing set" ($script:claudeCallCount -eq 0 -and -not (Test-Path Env:\ANTHROPIC_BASE_URL))
    Clear-SwitchEnv; Set-AugureFixture
    $script:AugurePyStdout = New-AugureReport -Selectable @(@{ id = "rosedale-1"; context_window = 1048576 }, @{ id = "rosedale-2"; context_window = 1048576 })
    $script:AugureChoice = "2"
    $null = & { claude-augure -Profile dev } *>&1
    Check "model answer 2 selects the second listed model" ($env:ANTHROPIC_MODEL -eq "augure-dev/rosedale-2")

    # 10m. the MCP key reaches the child environment only, never its arguments or the session
    Clear-SwitchEnv; Set-AugureFixture
    $null = & { claude-augure -Profile dev } *>&1
    $pyArgs = @(Get-AugurePyField 'Arguments') -join " "
    $childEnvMap = Get-AugurePyField 'Environment'
    Check "MCP key value absent from the python arguments" (-not ($pyArgs -match "user-mcp-key"))
    Check "MCP key handed to the child environment under its name" ($null -ne $childEnvMap -and $childEnvMap["AUGURE_MCP_KEY"] -eq "user-mcp-key")
    Check "MCP key never placed in the session environment" (-not (Test-Path Env:\AUGURE_MCP_KEY))

    # 10m2. the child receives the USER-scope MCP key, never a value planted in this session.
    #       The session copy is planted with a different value; the User reader (the fixture)
    #       returns "user-mcp-key". A production that read $env:AUGURE_MCP_KEY would hand the
    #       planted value to the child and fail here. The session copy must also survive untouched.
    Clear-SwitchEnv; Set-AugureFixture
    $env:AUGURE_MCP_KEY = "planted-session-mcp-value"
    $null = & { claude-augure -Profile dev } *>&1
    $plantedChildEnv = Get-AugurePyField 'Environment'
    Check "child receives the USER MCP key, not the planted session value" ($null -ne $plantedChildEnv -and $plantedChildEnv["AUGURE_MCP_KEY"] -eq "user-mcp-key")
    Check "planted session AUGURE_MCP_KEY is left exactly as it was" ($env:AUGURE_MCP_KEY -eq "planted-session-mcp-value")
    Remove-Item Env:\AUGURE_MCP_KEY -ErrorAction SilentlyContinue

    # --- 6e. Issue #75: the proxy address is refused unless loopback, the port is an integer 1..65535,
    #         and the liveness route must answer 2xx. Nothing is redirected on a refusal. ---
    $script:SettingsOverride = @{}
    $script:ProbeCalls  = 0
    $script:ProbeThrow  = $false
    $script:ProbeStatus = 200

    function Read-AugureDataFile {
        param([Parameter(Mandatory)][string]$Name)
        $doc = & $realReadAugureDataFile -Name $Name
        if ($Name -eq 'augure-settings.json') {
            foreach ($key in $script:SettingsOverride.Keys) { $doc.$key.value = $script:SettingsOverride[$key] }
        }
        return $doc
    }
    function Invoke-WebRequest {
        param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
        $script:ProbeCalls++
        if ($script:ProbeThrow) { throw "shadowed: no answer" }
        return [pscustomobject]@{ StatusCode = $script:ProbeStatus }
    }

    $badAddresses = @(
        @{ Name = "proxy host 0.0.0.0 refused";      Host_ = "0.0.0.0";     Port = 4000 },
        @{ Name = "proxy host example.org refused";  Host_ = "example.org"; Port = 4000 },
        @{ Name = "proxy port 0 refused";            Host_ = "127.0.0.1";   Port = 0 },
        @{ Name = "proxy port 70000 refused";        Host_ = "127.0.0.1";   Port = 70000 },
        @{ Name = "proxy port non-integer refused";  Host_ = "127.0.0.1";   Port = "4000x" }
    )
    foreach ($case in $badAddresses) {
        Clear-SwitchEnv
        Set-AugureFixture
        $script:SettingsOverride = @{ proxy_host = $case.Host_; proxy_port = $case.Port }
        $script:claudeCallCount = 0
        $null = & { claude-augure -Profile dev } *>&1
        Check ("$($case.Name): claude not started")            ($script:claudeCallCount -eq 0)
        Check ("$($case.Name): no base url set")               (-not (Test-Path Env:\ANTHROPIC_BASE_URL))
        Check ("$($case.Name): master key never assigned")     (-not (Test-Path Env:\ANTHROPIC_AUTH_TOKEN))
    }
    $script:SettingsOverride = @{}

    # The liveness answer itself: only a 2xx counts as up.
    Set-Item -Path function:Test-AugureProxy -Value $realTestAugureProxy
    $probeUrl = "http://127.0.0.1:4000/health/liveliness"
    $script:ProbeStatus = 500
    $live500 = & $realTestAugureProxy -Url $probeUrl -TimeoutSec 5
    Check "liveness status 500 is down" (-not $live500)
    $script:ProbeStatus = 401
    $live401 = & $realTestAugureProxy -Url $probeUrl -TimeoutSec 5
    Check "liveness status 401 is down" (-not $live401)
    $script:ProbeStatus = 200
    $live200 = & $realTestAugureProxy -Url $probeUrl -TimeoutSec 5
    Check "liveness status 200 is up"   ($live200 -eq $true)
    $script:ProbeThrow = $true
    $liveDown = & $realTestAugureProxy -Url $probeUrl -TimeoutSec 5
    Check "no answer is down"           (-not $liveDown)
    $script:ProbeThrow = $false

    # End to end through claude-augure with the real liveness check: 500 refuses, 200 proceeds.
    Clear-SwitchEnv
    Set-AugureFixture
    $script:ProbeStatus = 500
    $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "claude-augure refuses a 500 liveness answer" ($script:claudeCallCount -eq 0 -and -not (Test-Path Env:\ANTHROPIC_BASE_URL))
    Clear-SwitchEnv
    Set-AugureFixture
    $script:ProbeStatus = 200
    $script:claudeCallCount = 0
    $null = & { claude-augure -Profile dev } *>&1
    Check "claude-augure proceeds on a 200 liveness answer" ($script:claudeCallCount -eq 1)

    Clear-SwitchEnv

    # Invoke-AugureModelList must be bounded even when the child never exits and writes
    # nothing (R10). Before the fix, stderr was read synchronously, so the call blocked
    # until the child exited and the timeout never fired. The whole call runs in a job with
    # an outer bound so a regression fails here instead of hanging the verifier.
    # Each case runs in a job with an outer bound, so a regression (a blocked read) fails the
    # check instead of hanging the verifier. case: hang = child never exits; exit = child exits
    # -1 quickly with stderr; grand = child exits at once but a grandchild keeps stdout open.
    $marker = "augure-timeout-" + [guid]::NewGuid().ToString("N")
    $psExe  = (Get-Process -Id $PID).Path
    function Start-ListingCase([string]$Case, [string]$Exe) {
        $job = Start-Job -ScriptBlock {
            param($script, $exe, $case, $marker)
            . $script
            # grand: the outer child starts a grandchild that inherits its stdout and exits at
            # once. The grandchild's command line carries the marker, so it can be found and killed.
            $gc = "-NoProfile -Command Start-Sleep 30 #$marker"
            $outer = '$p = New-Object System.Diagnostics.ProcessStartInfo; $p.FileName = "powershell.exe"; $p.Arguments = ''' + $gc + '''; $p.UseShellExecute = $false; [void][System.Diagnostics.Process]::Start($p)'
            $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($outer))
            $childArgs = switch ($case) {
                'hang'  { @('-NoProfile', '-Command', "Start-Sleep 60 #$marker") }
                'exit'  { @('-NoProfile', '-Command', "[Console]::Error.Write('real-failure-text'); exit -1") }
                'grand' { @('-NoProfile', '-EncodedCommand', $encoded) }
            }
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $r = Invoke-AugureModelList -Python $exe -Arguments $childArgs -Environment @{} -TimeoutMs 2000
            [pscustomobject]@{ Ms = $sw.ElapsedMilliseconds; ExitCode = $r.ExitCode; Stderr = $r.Stderr; TimedOut = $r.TimedOut }
        } -ArgumentList $ScriptUnderTest, $Exe, $Case, $marker
        return $job
    }

    # hang: a child that never exits is a timeout, and is killed.
    $job = Start-ListingCase -Case 'hang' -Exe $psExe
    $finished = Wait-Job $job -Timeout 15
    if ($finished) {
        $out = Receive-Job $job
        Check "hung model listing returns within 10 s" ($out.Ms -lt 10000)
        Check "hung model listing reports a timeout (exit -1)" ($out.ExitCode -eq -1)
        Check "hung model listing sets TimedOut" ($out.TimedOut -eq $true)
        Check "hung model listing names the timeout" ($out.Stderr -match 'timed out')
    } else {
        Check "hung model listing returns within 15 s (outer bound)" $false
        Stop-Job $job
    }
    Remove-Job $job -Force
    Start-Sleep -Milliseconds 500
    $survivors = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$marker*" })
    Check "timed-out child process is no longer running" ($survivors.Count -eq 0)
    foreach ($p in $survivors) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }

    # exit: a child that really exits -1 is a failure with its stderr, NOT a timeout.
    $job = Start-ListingCase -Case 'exit' -Exe $psExe
    $finished = Wait-Job $job -Timeout 15
    if ($finished) {
        $out = Receive-Job $job
        Check "a child exiting -1 quickly is not reported as a timeout" ($out.TimedOut -eq $false)
        Check "a child exiting -1 keeps exit code -1" ($out.ExitCode -eq -1)
        Check "a child exiting -1 returns its stderr" ($out.Stderr -match 'real-failure-text')
    } else {
        Check "a child exiting -1 returns within 15 s (outer bound)" $false
        Stop-Job $job
    }
    Remove-Job $job -Force

    # grand: the child exits at once, but a grandchild keeps stdout open. The call must return
    # within the bound with TimedOut, and the grandchild must be the one holding the pipe.
    $job = Start-ListingCase -Case 'grand' -Exe $psExe
    $finished = Wait-Job $job -Timeout 15
    if ($finished) {
        $out = Receive-Job $job
        Check "a grandchild holding stdout returns within 10 s" ($out.Ms -lt 10000)
        Check "a grandchild holding stdout sets TimedOut" ($out.TimedOut -eq $true)
    } else {
        Check "a grandchild holding stdout returns within 15 s (outer bound)" $false
        Stop-Job $job
    }
    Remove-Job $job -Force
    Start-Sleep -Milliseconds 500
    $grandchildren = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$marker*" })
    Check "the grandchild holding the pipe was really running" ($grandchildren.Count -gt 0)
    foreach ($p in $grandchildren) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }

    # claude-augure branches on TimedOut: a real -1 exit prints its stderr and starts nothing.
    Clear-SwitchEnv; Set-AugureFixture
    $script:AugurePyExit = -1
    $script:AugurePyStderr = "real-failure-text"
    $script:claudeCallCount = 0
    $said = (& { claude-augure -Profile dev } *>&1 | Out-String)
    Check "claude-augure prints the stderr of a real -1 exit" ($said -match "real-failure-text")
    Check "claude-augure does not call a real -1 exit a timeout" ($said -notmatch "timed out")
    Check "claude-augure starts nothing on a real -1 exit" ($script:claudeCallCount -eq 0)
    Clear-SwitchEnv; Set-AugureFixture
    $script:AugurePyExit = -1
    $script:AugurePyTimedOut = $true
    $said = (& { claude-augure -Profile dev } *>&1 | Out-String)
    Check "claude-augure reports TimedOut as a timeout" ($said -match "timed out")
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
