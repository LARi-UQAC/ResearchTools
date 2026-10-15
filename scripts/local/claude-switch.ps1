#Requires -Version 5.1
<#
.SYNOPSIS
    Switches the Claude Code session itself between three identities: a local
    Ollama model (direct, no proxy), the Augure cloud endpoint, and the
    default Anthropic cloud.

.DESCRIPTION
    Three dot-sourced functions: claude-ollama (alias claude-local) redirects
    Claude Code to a model served locally by Ollama, claude-augure switches to
    the AugureAI endpoint with AUGUREAI_API_KEY, claude-cloud clears every
    redirection and returns to the default Anthropic cloud. Each function
    launches `claude` itself: normal usage is always one of the three, never
    bare `claude`, so no restore-on-exit is needed - every invocation is
    self-contained.

    The three functions share ONE save/restore mechanism (Save-OriginalEnvOnce
    / Restore-OriginalEnv, PR #61 review round 2, finding M1): the FIRST
    switch away from the default cloud identity in a given shell snapshots
    every routing variable (not only ANTHROPIC_API_KEY - a user's own
    corporate ANTHROPIC_BASE_URL, for instance, must come back too), and only
    claude-cloud restores that snapshot. Without the "once" guard, a second
    hop (e.g. ollama -> augure) would overwrite the snapshot with an
    intermediate state instead of the original (round 2, finding H2) - this
    was a real bug fixed in this revision, not a precaution.

    Independent of this repo's local-writer/local-coder bridge
    (.claude/skills/loop-engineer/scripts/ollama_bridge.py, model_resolver.py)
    in the sense that this redirects the Claude Code session itself, not an
    agent. The default local model tag IS resolved through model_resolver.py
    though (R2: that module is the only thing that names a tag), via a
    manually-adopted role, "session" (`--adopt-role session <tag> --reason
    "..."`), for a use - driving an entire interactive session - that
    qualification/tasks.json has no executable oracle for. Round 2's finding
    H1: resolving with `--role session` alone is NOT proof a session-specific
    tag was ever adopted - resolve() falls back to the global "current" tag
    silently otherwise, which contradicts this script's own "never a guessed
    tag" claim. Fixed by passing --require-role, which refuses instead of
    falling back.

    2026-01-16: Ollama exposes a native Anthropic Messages API
    (/v1/messages) since Ollama >= v0.14 (generalised v0.15+), so the LiteLLM
    proxy this script used before that date is retired: Claude Code points
    ANTHROPIC_BASE_URL straight at Ollama.

.NOTES
    A hand-maintained copy may exist in the operator's user profile (outside
    this repository); this versioned copy in ResearchTools is the source of
    reference.

    Local security (R34 / PR #61 review, finding L7): Ollama authenticates
    nobody on :11434. Any local process reaching that port receives the same
    prompts Claude Code would. Acceptable under this repository's
    single-user threat model (security.md), not beyond it.

    Known limit (PR #61 review, finding L2 / round 2 finding M3): Test-
    NetConnection is Windows-only, and the Ollama host is a fixed
    127.0.0.1 - OLLAMA_HOST is not consulted. Rewriting the reachability
    check for pwsh on Linux/macOS, and reading OLLAMA_HOST, is open work.

    Known limit (round 2, finding M5): this test is PowerShell, so it sits
    outside the Python-only green-stamp gate (run-offline-tests.ps1
    discovers only Test/test_*.py). Run manually, same family as
    scripts/test/verify-sync-writes.ps1 and the other PowerShell verify-*.ps1
    scripts already outside that gate by the same design. Stated here rather
    than silently assumed covered (R15).

.EXAMPLE
    . .\scripts\local\claude-switch.ps1
    claude-local
    claude-augure
    claude-cloud
    claude-local -Model qwen2.5-coder:7b -SessionName "PR61-local"
#>

# --- Configuration, in one place (R0) ---
# Operator / machine choices, not GPU measurements to keep in sync like
# .claude/local-model-config.json: one machine, one operator, nothing to
# re-sweep per card. Kept here rather than in an external JSON file so this
# script stays a plain dot-source with no extra read dependency; this
# decision is stated here rather than left silent (PR #61 review, findings
# L1/L8).
$script:OllamaHost = "127.0.0.1"
$script:OllamaPort = 11434
$script:ClientTimeoutMs = "600000"   # 10 min - slow local inference expected (see the "session" role below)
$script:AugureBaseUrl = "https://api.augureai.ca/v1"   # supplied by the operator, 2026-10-15

# Every variable either claude-ollama or claude-augure may set, so the SAME
# list drives both the save and the restore (round 2, finding M1 - restoring
# only the API key left a corporate ANTHROPIC_BASE_URL, for instance, gone
# for good).
$script:RoutingVarNames = @(
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_API_KEY"
)
$script:EnvSaved = $false   # explicit init: a read before any switch must never hit an
                            # unset variable under Set-StrictMode (round 2, finding M4)

function Save-OriginalEnvOnce {
    <#
    .SYNOPSIS
        Snapshots every routing variable's CURRENT value, once per shell, on
        the first switch away from the default cloud identity.

    .DESCRIPTION
        Called by claude-ollama and claude-augure, never by claude-cloud
        (which restores). The "once" guard is the fix for PR #61 review
        round 2's finding H2: an earlier revision saved unconditionally on
        every call, so a second hop between non-default identities (e.g.
        ollama then augure) overwrote the snapshot with an intermediate
        state instead of the true original, and claude-cloud then restored
        the wrong thing.

    Inputs:
        None.

    Outputs:
        None. Sets $script:SavedEnv (hashtable, variable name -> original
        value or $null) and $script:EnvSaved = $true, only on the first call
        since the last Restore-OriginalEnv.
    #>
    if ($script:EnvSaved) { return }
    $script:SavedEnv = @{}
    foreach ($name in $script:RoutingVarNames) {
        $script:SavedEnv[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    $script:EnvSaved = $true
}

function Restore-OriginalEnv {
    <#
    .SYNOPSIS
        Restores every routing variable to the value Save-OriginalEnvOnce
        captured, then clears the saved state.

    .DESCRIPTION
        Called only by claude-cloud. A no-op when nothing was ever saved in
        this shell (claude-cloud run as the very first call): an
        ANTHROPIC_API_KEY or ANTHROPIC_BASE_URL present for some other
        reason is left exactly as it was.

    Inputs:
        None.

    Outputs:
        None. Each name in $script:RoutingVarNames is set back to its saved
        value, or removed if the saved value was absent ($null).
    #>
    if (-not $script:EnvSaved) { return }
    foreach ($name in $script:RoutingVarNames) {
        $value = $script:SavedEnv[$name]
        if ($null -ne $value) { Set-Item "Env:\$name" $value }
        else { Remove-Item "Env:\$name" -ErrorAction SilentlyContinue }
    }
    $script:EnvSaved = $false
}

function Resolve-PythonInterpreter {
    <#
    .SYNOPSIS
        Resolves the Python interpreter the same way run-offline-tests.ps1
        does (R18: reuse, don't reinvent) - .venv-skills first, then .venv,
        then PATH. Round 2, finding M3: a bare `python` from PATH is not
        necessarily the project's own interpreter.

    Inputs:
        RepoRoot (string): the repository root to look for a venv under.

    Outputs:
        result (string | $null): the interpreter's full path, or $null if
        none of the three candidates resolves.
    #>
    param([Parameter(Mandatory)][string]$RepoRoot)
    $candidates = @(
        (Join-Path $RepoRoot ".venv-skills\Scripts\python.exe"),
        (Join-Path $RepoRoot ".venv\Scripts\python.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c -PathType Leaf) { return $c }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $onPath) { return $onPath.Source }
    return $null
}

function Resolve-SessionModelTag {
    <#
    .SYNOPSIS
        Resolves the default local model tag via model_resolver.py's
        manually-adopted "session" role (R2: never a hardcoded tag here).

    .DESCRIPTION
        Calls `model_resolver.py --resolve --role session --require-role`.
        Round 2, finding H1: `--role session` ALONE is not proof a
        session-specific tag was ever adopted - resolve() falls back
        silently to the global "current" tag (typically the small writer
        model) when no current_by_role["session"] entry exists, which
        contradicts this script's own "never a guessed tag" claim.
        --require-role makes the resolver refuse explicitly instead of
        falling back, so a fresh clone with no session adoption gets a clear
        refusal here rather than a session silently launched on the wrong
        model.

        Round 2, finding M3: takes the LAST non-empty output line (a
        multi-line stdout would otherwise make PowerShell return an array,
        and a bare .Trim() on an array throws) and resolves the interpreter
        through .venv-skills rather than a bare `python` from PATH.

    Inputs:
        None.

    Outputs:
        result (string | $null): the resolved tag, or $null when the
        resolver cannot be found, is not installed, or refuses (including
        the require-role refusal above) - never an invented tag (R8).
    #>
    $repoRoot = $null
    try {
        $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    } catch { }
    if (-not $repoRoot -and $env:RESEARCHTOOLS_ROOT) {
        $repoRoot = $env:RESEARCHTOOLS_ROOT
    }
    if (-not $repoRoot) { return $null }

    $resolverPath = Join-Path $repoRoot ".claude\skills\loop-engineer\scripts\model_resolver.py"
    if (-not (Test-Path $resolverPath)) { return $null }

    $python = Resolve-PythonInterpreter -RepoRoot $repoRoot
    if (-not $python) { return $null }

    $output = & $python $resolverPath --resolve --role session --require-role 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    # Wrapping the WHOLE pipeline in @(...) matters: PowerShell assigns $null (not an
    # empty array) when a pipeline yields zero objects, and $null.Count throws under
    # Set-StrictMode instead of reading as 0.
    $lines = @($output | Where-Object { $_.Trim() -ne "" })
    if ($lines.Count -eq 0) { return $null }
    return $lines[-1].Trim()
}

function Format-OllamaTag {
    <#
    .SYNOPSIS
        Normalizes a bare model name to "name:latest", matching the
        convention vram_probe.py's own tag parsing already uses (R18).

    .DESCRIPTION
        Round 2, finding M2: comparing tags with a bare exact-string match
        refused "qwen3.5" even though Ollama itself serves it as
        "qwen3.5:latest" and `ollama list` prints it that way.

    Inputs:
        Tag (string): a bare name or a "name:tag" pair.

    Outputs:
        result (string): the tag with ":latest" appended when it carried no
        tag of its own.
    #>
    param([Parameter(Mandatory)][string]$Tag)
    if ($Tag -notmatch ":") { return "${Tag}:latest" }
    return $Tag
}

function Test-OllamaHasModel {
    <#
    .SYNOPSIS
        Checks that the requested tag is actually installed, not merely that
        Ollama's port answers.

    .DESCRIPTION
        PR #61 review, finding #5: a reachable port is not proof the
        requested MODEL is present - without this check, the switch
        "succeeds" and Claude Code then fails on its first real request with
        "model not found". Both sides of the comparison are normalized via
        Format-OllamaTag (round 2, finding M2).

    Inputs:
        Tag (string): the tag to look for.

    Outputs:
        result (bool): $true when the normalized tag is in `ollama list`'s
        NAME column, $false otherwise (including when `ollama list` itself
        fails).
    #>
    param([Parameter(Mandatory)][string]$Tag)
    $raw = & ollama list 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $false }
    $installed = $raw -split "`n" | Select-Object -Skip 1 |
        ForEach-Object { Format-OllamaTag -Tag ($_ -split '\s+')[0] }
    return $installed -contains (Format-OllamaTag -Tag $Tag)
}

function claude-ollama {
    <#
    .SYNOPSIS
        Switches Claude Code to a local Ollama model, launching `claude`.

    .DESCRIPTION
        Refuses (never launching `claude`) when Ollama is not reachable on
        $script:OllamaHost:$script:OllamaPort, when no -Model is given and
        Resolve-SessionModelTag cannot resolve one, or when the resolved/
        given tag is not actually installed (Test-OllamaHasModel).

    Inputs:
        Model (string, optional): the tag to use. Defaults to
            Resolve-SessionModelTag's result.
        SessionName (string, optional): sets the terminal window title to
            "[LOCAL] <name>" (cosmetic only - see the module .DESCRIPTION).

    Outputs:
        None. On success, sets every routing variable and launches
        `claude`, after saving the prior environment once per shell
        (Save-OriginalEnvOnce).
    #>
    param(
        [string]$Model,
        [string]$SessionName
    )

    if (-not $Model) {
        $Model = Resolve-SessionModelTag
        if (-not $Model) {
            Write-Host "model_resolver.py could not be found, or has no tag adopted for the 'session' role. Pass -Model <tag> explicitly, or check RESEARCHTOOLS_ROOT." -ForegroundColor Red
            return
        }
    }

    # 1. Confirm Ollama answers before redirecting the agent to it - no silent
    #    start: a failure here must stop the switch, not launch Claude Code
    #    against a dead port.
    if (-not (Test-NetConnection -ComputerName $script:OllamaHost -Port $script:OllamaPort -WarningAction SilentlyContinue -InformationLevel Quiet)) {
        Write-Host "Ollama is not answering on ${script:OllamaHost}:${script:OllamaPort}. Start the Ollama service and retry." -ForegroundColor Red
        return
    }

    # 1b. The port answers, but is THIS model actually installed?
    if (-not (Test-OllamaHasModel -Tag $Model)) {
        Write-Host "Ollama answers but '$Model' is not in 'ollama list'. Run 'ollama pull $Model', or fix -Model." -ForegroundColor Red
        return
    }

    Save-OriginalEnvOnce

    # 2. Redirect the agent to Ollama (native Anthropic API, no proxy)
    $env:ANTHROPIC_BASE_URL         = "http://${script:OllamaHost}:${script:OllamaPort}"
    $env:ANTHROPIC_AUTH_TOKEN       = "ollama"            # bearer token Ollama expects, not an Anthropic key
    $env:ANTHROPIC_MODEL            = $Model
    $env:ANTHROPIC_SMALL_FAST_MODEL = $Model              # background tasks -> same model

    # 3. Timeout - slow local model. Client side (ms)
    $env:API_TIMEOUT_MS             = $script:ClientTimeoutMs

    # 4. 100% offline mode (cuts Anthropic telemetry/auto-update)
    $env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"

    Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[LOCAL] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> $Model (local, Ollama direct, no proxy)" -ForegroundColor Green
    claude
}

function claude-augure {
    <#
    .SYNOPSIS
        Switches Claude Code to the AugureAI cloud endpoint, launching
        `claude`.

    .DESCRIPTION
        Refuses (never launching `claude`, touching no environment variable)
        when AUGUREAI_API_KEY is not set. Clears any Ollama-routing
        variables a prior claude-ollama call left behind in this shell,
        since they would otherwise conflict with Augure's own endpoint.

    Inputs:
        SessionName (string, optional): sets the terminal window title to
            "[AUGURE] <name>" (cosmetic only).

    Outputs:
        None. On success, sets ANTHROPIC_BASE_URL/ANTHROPIC_API_KEY and
        launches `claude`, after saving the prior environment once per shell
        (Save-OriginalEnvOnce).
    #>
    param([string]$SessionName)

    if (-not $env:AUGUREAI_API_KEY) {
        Write-Host "AUGUREAI_API_KEY is not set in the environment. Cannot switch to Augure." -ForegroundColor Red
        return
    }

    # Clear any residual local redirection: if claude-ollama ran earlier in
    # this shell without an intervening claude-cloud, ANTHROPIC_AUTH_TOKEN/
    # MODEL/... would still point at Ollama and conflict with Augure's own
    # endpoint.
    Remove-Item `
        Env:\ANTHROPIC_AUTH_TOKEN, `
        Env:\ANTHROPIC_MODEL, `
        Env:\ANTHROPIC_SMALL_FAST_MODEL, `
        Env:\API_TIMEOUT_MS, `
        Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC `
        -ErrorAction SilentlyContinue

    Save-OriginalEnvOnce
    $env:ANTHROPIC_BASE_URL = $script:AugureBaseUrl
    $env:ANTHROPIC_API_KEY  = $env:AUGUREAI_API_KEY

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[AUGURE] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> Augure ($script:AugureBaseUrl)" -ForegroundColor Magenta
    claude
}

function claude-cloud {
    <#
    .SYNOPSIS
        Clears every local/Augure redirection and returns Claude Code to the
        default Anthropic cloud, launching `claude`.

    .DESCRIPTION
        Restores every routing variable to whatever it was before the FIRST
        switch away from the default identity in this shell (round 2,
        finding M1: earlier revisions restored only ANTHROPIC_API_KEY,
        losing a user's own ANTHROPIC_BASE_URL - e.g. a corporate gateway -
        for good). A no-op restore when neither claude-ollama nor
        claude-augure ran yet in this shell: a variable already present for
        some other reason is left untouched.

    Inputs:
        SessionName (string, optional): sets the terminal window title to
            "[CLOUD] <name>" (cosmetic only).

    Outputs:
        None. Launches `claude` after restoring the environment.
    #>
    param([string]$SessionName)

    Restore-OriginalEnv

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[CLOUD] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> Anthropic Cloud." -ForegroundColor Yellow
    claude
}

Set-Alias claude-local claude-ollama   # both names work
