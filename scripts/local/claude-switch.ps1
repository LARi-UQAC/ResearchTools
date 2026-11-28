#Requires -Version 5.1
<#
.SYNOPSIS
    Switches the Claude Code session itself between three identities: a local
    Ollama model (direct, no proxy), the Augure cloud endpoint, and the
    default Anthropic cloud.

.DESCRIPTION
    Three dot-sourced functions: claude-ollama (alias claude-local) redirects
    Claude Code to a model served locally by Ollama, claude-augure switches to
    AugureAI through a local LiteLLM proxy (Issue #112: profile, keys and model
    chosen from scripts\local\augure\), claude-cloud clears every
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
    claude-augure -Profile dev
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
$script:AugureDataDir = Join-Path $PSScriptRoot "augure"   # settings, models and profiles of claude-augure (Issue #112)

# Every variable either claude-ollama or claude-augure may set, so the SAME
# list drives both the save and the restore (round 2, finding M1 - restoring
# only the API key left a corporate ANTHROPIC_BASE_URL, for instance, gone
# for good).
$script:RoutingVarNames = @(
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS"
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
        Resolves the Python interpreter through scripts\lib\rt-venv.ps1, the
        single owner of that decision (R18: reuse, don't reinvent), the same
        one run-offline-tests.ps1 uses. Round 2, finding M3: a bare `python`
        from PATH is not necessarily the project's own interpreter, and since
        2026-10-16 it is never taken silently (R8): with no .venv-skills here
        or in the main clone the reason is printed as a warning and $null is
        returned, which the caller reads as "no resolver available".

    Inputs:
        RepoRoot (string): the repository root to look for a venv under.

    Outputs:
        result (string | $null): the interpreter's full path, or $null if
        no environment exists (the refusal text goes to the warning stream).
    #>
    param([Parameter(Mandatory)][string]$RepoRoot)
    $helper = Join-Path $RepoRoot "scripts\lib\rt-venv.ps1"
    if (-not (Test-Path $helper)) {
        Write-Warning "scripts/lib/rt-venv.ps1 is missing from $RepoRoot, so no interpreter can be resolved."
        return $null
    }
    . $helper
    $resolved = Resolve-RtVenvPython -RepoRoot $RepoRoot
    if ($null -eq $resolved.Python) {
        Write-Warning $resolved.Message
        return $null
    }
    return $resolved.Python
}

function Get-ResolverInvocation {
    <#
    .SYNOPSIS
        Finds model_resolver.py and the interpreter that runs it, once, for every caller that
        asks the resolver something (the tag, the window).

    Outputs:
        result (hashtable | $null): @{ Python; Resolver }, or $null when the repository root,
        the resolver script or the interpreter cannot be found.
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
    return @{ Python = $python; Resolver = $resolverPath }
}

function Resolve-SessionWindow {
    <#
    .SYNOPSIS
        The context window, in tokens, of the model the manually adopted "session" role
        resolves to, so claude-ollama can tell Claude Code (CLAUDE_CODE_MAX_CONTEXT_TOKENS)
        instead of letting it assume 200K for an unrecognised model ID.

    .DESCRIPTION
        Asks `model_resolver.py --window --role session`. The window is the SESSION role's,
        so it is answered only when the requested tag IS that role's tag: the window of one
        model is never lent to another (R8).

    Inputs:
        ForTag (string): the tag claude-ollama is about to route to.

    Outputs:
        result (int | $null): the window, or $null when the tag is not the session role's,
        the resolver cannot be reached, or the window is unknown.
    #>
    param([Parameter(Mandatory)][string]$ForTag)
    $sessionTag = Resolve-SessionModelTag
    if (-not $sessionTag -or (Format-OllamaTag $sessionTag) -ne (Format-OllamaTag $ForTag)) { return $null }
    $context = Get-ResolverInvocation
    if (-not $context) { return $null }
    $output = & $context.Python $context.Resolver --window --role session 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    $lines = @($output | Where-Object { $_.Trim() -ne "" })
    if ($lines.Count -eq 0) { return $null }
    $parsed = 0
    if (-not [int]::TryParse($lines[-1].Trim(), [ref]$parsed) -or $parsed -le 0) { return $null }
    return $parsed
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
    $context = Get-ResolverInvocation
    if (-not $context) { return $null }
    $python = $context.Python
    $resolverPath = $context.Resolver

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

    # 1c. Tell Claude Code the window of the model it is about to talk to. An unrecognised
    #     model ID is assumed to have 200K, so a 262K session would compact too early (and a
    #     smaller one too late). Only the session role's own window is known here; any other
    #     tag leaves the variable unset and says so.
    $window = Resolve-SessionWindow -ForTag $Model
    if ($window) {
        $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "$window"
    } else {
        Remove-Item Env:\CLAUDE_CODE_MAX_CONTEXT_TOKENS -ErrorAction SilentlyContinue
        Write-Host "Window of '$Model' is not recorded, so Claude Code will assume 200K tokens. Record it with model_resolver.py --adopt-role session <tag> --reason ... --num-ctx <N>." -ForegroundColor Yellow
    }

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

function Read-AugureDataFile {
    <#
    .SYNOPSIS
        Reads one JSON data file of the AugureAI route, from scripts\local\augure\.

    Inputs:
        Name (string): the file name.

    Outputs:
        result (PSCustomObject): the parsed document. Its entries are {value, provenance}.
    #>
    param([Parameter(Mandatory)][string]$Name)
    return (Get-Content -Raw -Encoding UTF8 -Path (Join-Path $script:AugureDataDir $Name) | ConvertFrom-Json)
}

function Get-AugureEntryValue {
    <#
    .SYNOPSIS
        Returns the "value" of one {value, provenance} entry, refusing a missing one by name (R3).

    Inputs:
        Container (PSCustomObject): an object of a data file (the settings, or one profile).
        Key (string): the entry name.

    Outputs:
        result: the entry's value, as written in the file.

    Raises:
        Throws a message naming the key when the entry is absent.
    #>
    param([Parameter(Mandatory)]$Container, [Parameter(Mandatory)][string]$Key)
    $property = $Container.PSObject.Properties[$Key]
    if ($null -eq $property -or $null -eq $property.Value.PSObject.Properties['value']) {
        throw "'$Key' is missing from the AugureAI data files"
    }
    return $property.Value.value
}

function ConvertTo-AugureIndex {
    <#
    .SYNOPSIS
        Turns a menu answer into a zero-based index, or -1 when it is not a listed number.

    .DESCRIPTION
        A menu never guesses: an answer that is not a whole number from 1 to Count is refused
        by the caller, not repeated and not replaced by a default.

    Inputs:
        Answer (string): the raw answer.
        Count (int): the number of entries offered.

    Outputs:
        result (int): the zero-based index, or -1.
    #>
    param([AllowNull()][string]$Answer, [Parameter(Mandatory)][int]$Count)
    $number = 0
    if ($null -eq $Answer -or -not [int]::TryParse($Answer.Trim(), [ref]$number)) { return -1 }
    if ($number -lt 1 -or $number -gt $Count) { return -1 }
    return $number - 1
}

function Test-AugureProxy {
    <#
    .SYNOPSIS
        One liveness request to the LiteLLM proxy, bounded by its timeout (R10).

    Inputs:
        Url (string): the liveness URL.
        TimeoutSec (int): seconds to wait.

    Outputs:
        result (bool): $true only when the liveness route answers with a 2xx status. Any other
        status (401, 500 and so on), a timeout or a connection failure is $false: an error
        answer from something on the port is not the LiteLLM proxy being up (Issue #75).
    #>
    param([Parameter(Mandatory)][string]$Url, [Parameter(Mandatory)][int]$TimeoutSec)
    try {
        $answer = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        $code = [int]$answer.StatusCode
        return ($code -ge 200 -and $code -le 299)
    } catch {
        return $false
    }
}

function Invoke-AugureModelList {
    <#
    .SYNOPSIS
        Runs `augure_models.py list` in a child process, with the MCP key in ITS environment only.

    .DESCRIPTION
        The key is set on ProcessStartInfo.EnvironmentVariables, so it never appears on the
        command line (visible to any process) and never in this session's environment.
        Output is read asynchronously so a full stderr pipe cannot block the child. The wait is
        bounded (R10).

    Inputs:
        Python (string): the interpreter, from Resolve-PythonInterpreter.
        Arguments (string[]): the script path and its arguments; never a secret.
        Environment (hashtable): extra child variables, here the MCP key only.
        TimeoutMs (int): the bound on the whole child process.

    Outputs:
        result (hashtable): @{ ExitCode; TimedOut; Stdout; Stderr }. TimedOut is $true only when
        the bound expired; a child that really exits -1 has TimedOut $false and its stderr kept.
    #>
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][int]$TimeoutMs
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Python
    $startInfo.Arguments = (@($Arguments) | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($name in $Environment.Keys) { $startInfo.EnvironmentVariables[$name] = [string]$Environment[$name] }

    $process = [System.Diagnostics.Process]::Start($startInfo)
    # Both streams are drained asynchronously: a synchronous read blocks until the child closes
    # the pipe, i.e. until it exits, so the bounded wait below would never be reached (R10).
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $timeout = @{ ExitCode = -1; TimedOut = $true; Stdout = ""; Stderr = "the model listing timed out" }
    if (-not $process.WaitForExit($TimeoutMs)) {
        # Kill the whole tree (a launcher may have spawned children holding the pipes), then fall
        # back to the process itself. Either failing must not hide the timeout result.
        try { & taskkill.exe /T /F /PID $process.Id *> $null } catch { }
        try { if (-not $process.HasExited) { $process.Kill() } } catch { }
        return $timeout
    }
    # The child exited, but a grandchild may still hold the pipes open. Both reads share the time
    # left of the same bound, so the call returns within TimeoutMs whatever the pipes do (R10).
    $remainingMs = [int][Math]::Max(0, $TimeoutMs - $clock.ElapsedMilliseconds)
    $readsDone = [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask), $remainingMs)
    if (-not $readsDone) {
        # The orphaned grandchild is not reachable through the dead parent's tree, so only the
        # result is bounded here; the pipes are abandoned with the call.
        return $timeout
    }
    return @{ ExitCode = $process.ExitCode; TimedOut = $false; Stdout = $stdoutTask.Result; Stderr = $stderrTask.Result }
}

function Read-AugureUserEnv {
    <#
    .SYNOPSIS
        Reads one environment variable at USER scope, the only source of the AugureAI keys.

    .DESCRIPTION
        Never the process copy: a VS Code process was measured holding a stale AUGUREAI_API_KEY
        (48 characters, the User value is 52) that AugureAI refused with 401 (Issue #112).

    Inputs:
        Name (string): the variable name.

    Outputs:
        result (string | $null): the User-scope value, or $null when unset.
    #>
    param([Parameter(Mandatory)][string]$Name)
    return [Environment]::GetEnvironmentVariable($Name, 'User')
}

function Read-AugureChoice {
    <#
    .SYNOPSIS
        Reads one menu answer from the operator. The only Read-Host call of the AugureAI route.

    Inputs:
        Prompt (string): the question shown.

    Outputs:
        result (string): the raw answer, validated by the caller.
    #>
    param([Parameter(Mandatory)][string]$Prompt)
    return Read-Host -Prompt $Prompt
}

function claude-augure {
    <#
    .SYNOPSIS
        Switches Claude Code to AugureAI through the local LiteLLM proxy, launching `claude`.

    .DESCRIPTION
        Six steps, every refusal before the first routing variable changes:
          1. the profile: -Profile, else a numbered menu of augure-profiles.json;
          2. the profile's keys, read at USER scope (Read-AugureUserEnv), missing or empty refused by name;
          3. the proxy answers its liveness route, else refused naming litellm-autostart.ps1;
          4. augure_models.py list --profile P --json, the MCP key in the child environment only;
          5. the model: -Model must be selectable, the only selectable one is used, several are a menu;
          6. the routing variables.
        A menu answer that is not a listed number is refused, never repeated and never defaulted.

        Separating the dev and chat keys later is ONE line of augure-profiles.json (the profile's
        api_key_env or mcp_key_env), no code change here (owner, 2026-11-27).

    Inputs:
        Profile (string, optional): a profile name of augure-profiles.json.
        Model (string, optional): a model id the account can use.
        SessionName (string, optional): window title "[AUGURE] <name>" (cosmetic only).

    Outputs:
        None. On success sets ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN (the master key),
        ANTHROPIC_MODEL and ANTHROPIC_SMALL_FAST_MODEL (augure-<profile>/<id>),
        CLAUDE_CODE_MAX_CONTEXT_TOKENS (the model's window) and removes ANTHROPIC_API_KEY,
        after saving the prior environment once per shell (Save-OriginalEnvOnce).
    #>
    param([string]$Profile, [string]$Model, [string]$SessionName)

    try {
        $settings = Read-AugureDataFile -Name 'augure-settings.json'
        $profilesDoc = Read-AugureDataFile -Name 'augure-profiles.json'
    } catch {
        Write-Host "The AugureAI data files cannot be read: $($_.Exception.Message)" -ForegroundColor Red
        return
    }
    $names = @($profilesDoc.profiles.PSObject.Properties | ForEach-Object { $_.Name })

    # 1. Profile. Adding a profile, or giving one its own keys, is a data change in augure-profiles.json.
    if (-not $Profile) {
        Write-Host "AugureAI profile:" -ForegroundColor Magenta
        for ($i = 0; $i -lt $names.Count; $i++) { Write-Host ("  {0}. {1}" -f ($i + 1), $names[$i]) }
        $answer = Read-AugureChoice -Prompt "Profile number"
        $index = ConvertTo-AugureIndex -Answer $answer -Count $names.Count
        if ($index -lt 0) {
            Write-Host "'$answer' is not a number between 1 and $($names.Count). Nothing was changed; run claude-augure again." -ForegroundColor Red
            return
        }
        $Profile = $names[$index]
    }
    if ($names -notcontains $Profile) {
        Write-Host "Unknown AugureAI profile '$Profile' (known: $($names -join ', '))." -ForegroundColor Red
        return
    }

    try {
        $profileEntry = $profilesDoc.profiles.PSObject.Properties[$Profile].Value
        $apiKeyVar    = Get-AugureEntryValue -Container $profileEntry -Key 'api_key_env'
        $mcpKeyVar    = Get-AugureEntryValue -Container $profileEntry -Key 'mcp_key_env'
        $masterKeyVar = Get-AugureEntryValue -Container $settings -Key 'master_key_env'
        $proxyHost    = Get-AugureEntryValue -Container $settings -Key 'proxy_host'
        $proxyPort    = Get-AugureEntryValue -Container $settings -Key 'proxy_port'
        $livenessPath = Get-AugureEntryValue -Container $settings -Key 'liveness_path'
        $timeoutSec   = Get-AugureEntryValue -Container $settings -Key 'http_timeout_s'
        $modelPrefix  = Get-AugureEntryValue -Container $settings -Key 'model_prefix'
    } catch {
        Write-Host "AugureAI settings are incomplete: $($_.Exception.Message)" -ForegroundColor Red
        return
    }

    # 0. The proxy address, checked before any key is read or any variable is set (Issue #75).
    #    The host rule mirrors Resolve-LitellmStartDecision in scripts\local\augure\litellm-autostart.ps1:
    #    only 127.0.0.1. Change both together. The port must be an integer from 1 to 65535.
    if ($proxyHost -ne '127.0.0.1') {
        Write-Host "proxy_host is '$proxyHost' in augure-settings.json; only 127.0.0.1 is allowed (loopback only). Nothing was changed." -ForegroundColor Red
        return
    }
    $portOk = ($proxyPort -is [int] -or $proxyPort -is [long]) -and ($proxyPort -ge 1) -and ($proxyPort -le 65535)
    if (-not $portOk) {
        Write-Host "proxy_port is '$proxyPort' in augure-settings.json; it must be an integer from 1 to 65535. Nothing was changed." -ForegroundColor Red
        return
    }

    # 2. Keys, at USER scope. The process copy is never read.
    $keys = [ordered]@{}
    foreach ($var in @($apiKeyVar, $mcpKeyVar, $masterKeyVar)) {
        $keys[$var] = Read-AugureUserEnv -Name $var
        if ([string]::IsNullOrWhiteSpace($keys[$var])) {
            Write-Host "$var is not set, or is empty, at the User scope. Set it, then open a new terminal." -ForegroundColor Red
            return
        }
    }

    # 3. The proxy must answer its liveness route before anything is redirected to it.
    $base = "http://${proxyHost}:${proxyPort}"
    if (-not (Test-AugureProxy -Url ($base + $livenessPath) -TimeoutSec $timeoutSec)) {
        Write-Host "The LiteLLM proxy does not answer on $base. Start it with scripts\local\augure\litellm-autostart.ps1, then retry." -ForegroundColor Red
        return
    }

    # 4. Live list of the models this profile may use. The MCP key travels in the child environment only.
    $repoRoot = (Resolve-Path (Join-Path $script:AugureDataDir "..\..\..")).Path
    $python = Resolve-PythonInterpreter -RepoRoot $repoRoot
    if (-not $python) { return }
    $childEnv = @{}
    $childEnv[$mcpKeyVar] = $keys[$mcpKeyVar]
    # One list is three MCP requests, each bounded by http_timeout_s (R10).
    $listTimeoutMs = [int]($timeoutSec * 1000 * 3)
    $result = Invoke-AugureModelList -Python $python `
        -Arguments @((Join-Path $script:AugureDataDir 'augure_models.py'), 'list', '--profile', $Profile, '--json') `
        -Environment $childEnv -TimeoutMs $listTimeoutMs

    $report = $null
    try { $report = $result.Stdout | ConvertFrom-Json } catch { $report = $null }
    $selectable = @()
    $refused = @()
    if ($null -ne $report) {
        $selectable = @($report.selectable)
        $refused = @($report.refused)
    }
    if ($result.TimedOut) {
        Write-Host "The model listing for profile ${Profile} timed out after $listTimeoutMs ms; nothing was changed." -ForegroundColor Red
        return
    }
    if ($result.ExitCode -ne 0 -or $selectable.Count -eq 0) {
        Write-Host "No model can be used with profile ${Profile}." -ForegroundColor Red
        foreach ($item in $refused) { Write-Host "  $($item.id): $($item.reason)" -ForegroundColor Red }
        if ($result.Stderr) { Write-Host $result.Stderr.Trim() -ForegroundColor Red }
        return
    }

    # 5. Model: -Model must be selectable; one selectable model is used; several are a menu.
    if ($Model) {
        $chosen = @($selectable | Where-Object { $_.id -eq $Model })
        if ($chosen.Count -eq 0) {
            $why = @($refused | Where-Object { $_.id -eq $Model } | ForEach-Object { $_.reason })
            if ($why.Count -eq 0) { $why = @('it is not in the list the account returned') }
            Write-Host "Model '$Model' cannot be used with profile ${Profile}: $($why[0])" -ForegroundColor Red
            return
        }
        $chosenModel = $chosen[0]
    } elseif ($selectable.Count -eq 1) {
        $chosenModel = $selectable[0]
        Write-Host "Model: $($chosenModel.id) ($($chosenModel.context_window) tokens)" -ForegroundColor Magenta
    } else {
        Write-Host "Models for profile ${Profile}:" -ForegroundColor Magenta
        for ($i = 0; $i -lt $selectable.Count; $i++) {
            Write-Host ("  {0}. {1} ({2} tokens)" -f ($i + 1), $selectable[$i].id, $selectable[$i].context_window)
        }
        $answer = Read-AugureChoice -Prompt "Model number"
        $index = ConvertTo-AugureIndex -Answer $answer -Count $selectable.Count
        if ($index -lt 0) {
            Write-Host "'$answer' is not a number between 1 and $($selectable.Count). Nothing was changed; run claude-augure again." -ForegroundColor Red
            return
        }
        $chosenModel = $selectable[$index]
    }
    $modelRef = "$modelPrefix$Profile/$($chosenModel.id)"
    $window = [int]$chosenModel.context_window

    # 6. Routing. Every refusal above returned before this point.
    Save-OriginalEnvOnce
    Remove-Item Env:\ANTHROPIC_API_KEY, Env:\API_TIMEOUT_MS, Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC -ErrorAction SilentlyContinue
    $env:ANTHROPIC_BASE_URL         = $base
    $env:ANTHROPIC_AUTH_TOKEN       = $keys[$masterKeyVar]
    $env:ANTHROPIC_MODEL            = $modelRef
    $env:ANTHROPIC_SMALL_FAST_MODEL = $modelRef
    $env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "$window"

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[AUGURE] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> AugureAI $modelRef through $base" -ForegroundColor Magenta
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
