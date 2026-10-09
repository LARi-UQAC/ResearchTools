#Requires -Version 5.1
<#
.SYNOPSIS
    Bascule Claude Code lui-meme entre un modele Ollama local (direct, sans
    proxy) et le cloud Anthropic.

.DESCRIPTION
    Deux fonctions dot-sourcees : claude-ollama (alias claude-local) redirige
    Claude Code vers un modele Ollama servi en local, claude-cloud efface la
    redirection et revient au cloud Anthropic. Chaque fonction lance elle-meme
    `claude` : l'usage normal est toujours `claude-local` ou `claude-cloud`,
    jamais `claude` tout seul, donc aucune restauration automatique a la
    sortie n'est necessaire - chaque invocation est auto-suffisante.

    INDEPENDANT du pont local-writer/local-coder de ce depot
    (.claude/skills/loop-engineer/scripts/ollama_bridge.py, model_resolver.py)
    au sens ou ce script redirige la session Claude Code elle-meme, pas les
    agents de ce depot. Mais depuis la revue de PR #61 (R2), le modele par
    defaut n'est PLUS un tag en dur : model_resolver.py reste la SEULE chose
    qui nomme un tag, via un nouveau role manuel "session"
    (`--adopt-role session <tag> --reason "..."`) pour un usage - piloter une
    session Claude Code entiere - qu'aucune tache de qualification/tasks.json
    ne peut noter par un oracle executable. -Model reste disponible pour
    outrepasser explicitement le resolver.

    MAJ 2026-10-08 : Ollama expose nativement l'API Anthropic Messages
    (/v1/messages) depuis la mise a jour du 16 janvier 2026 (>= v0.14,
    generalisee v0.15+). Le proxy LiteLLM (Anthropic -> OpenAI -> Ollama)
    n'est plus necessaire : Claude Code pointe directement sur Ollama.

.NOTES
    Une copie geree a la main peut exister dans le profil utilisateur de
    l'operateur (hors depot) ; cette copie versionnee dans ResearchTools en
    est la source de reference.

    Securite locale (R34/revue PR #61, finding L7) : Ollama n'authentifie
    personne sur :11434. Tout processus local qui atteint ce port recoit les
    memes prompts que Claude Code. Acceptable dans le modele de menace a un
    seul utilisateur de ce depot (security.md), pas au-dela.

    Limite connue (revue PR #61, finding L2) : Test-NetConnection est
    Windows-only. Sous pwsh Linux/macOS, la verification de joignabilite doit
    etre reecrite (ex. Test-Connection ou un socket .NET direct).

.EXAMPLE
    . .\scripts\local\claude-switch.ps1
    claude-local
    claude-cloud
    claude-local -Model qwen2.5-coder:7b -SessionName "PR61-local"
#>

# --- Configuration, en un seul endroit (R0) ---
# Choix personnels de l'operateur / de cette machine, pas des mesures GPU a
# tenir a jour comme .claude/local-model-config.json : une seule machine, un
# seul operateur, rien a resweeper par carte. Regroupes ici plutot que dans
# un fichier JSON externe pour que ce script reste un simple dot-source sans
# dependance de lecture supplementaire ; cette decision est documentee ici
# plutot que silencieuse (revue PR #61, findings L1/8).
$script:OllamaHost = "127.0.0.1"
$script:OllamaPort = 11434
$script:ClientTimeoutMs = "600000"   # 10 min - mesure lente attendue (voir le role "session" ci-dessous)

function Resolve-SessionModelTag {
    <#
    .SYNOPSIS
        Resout le tag par defaut via model_resolver.py --resolve --role
        session (R2 : jamais de tag en dur ici). Retourne $null si le
        resolver est introuvable ou refuse - jamais un tag invente (R8).
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

    $tag = & python $resolverPath --resolve --role session 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $tag) { return $null }
    return $tag.Trim()
}

function Test-OllamaHasModel {
    param([Parameter(Mandatory)][string]$Tag)
    # Finding #5 (revue PR #61) : un port ouvert ne prouve pas que LE MODELE
    # demande est present - sans ca, la bascule "reussit" puis Claude Code
    # echoue a la premiere requete avec "model not found".
    $raw = & ollama list 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $false }
    $installed = $raw -split "`n" | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] }
    return $installed -contains $Tag
}

function claude-ollama {
    param(
        [string]$Model,
        [string]$SessionName
    )

    if (-not $Model) {
        $Model = Resolve-SessionModelTag
        if (-not $Model) {
            Write-Host "model_resolver.py introuvable ou sans tag pour le role 'session'. Passe -Model <tag> explicitement, ou verifie RESEARCHTOOLS_ROOT." -ForegroundColor Red
            return
        }
    }

    # 1. Verifie qu'Ollama repond avant de rediriger l'agent dessus (pas de
    #    demarrage silencieux : un echec ici doit arreter la bascule, pas
    #    lancer Claude Code contre un port mort).
    if (-not (Test-NetConnection -ComputerName $script:OllamaHost -Port $script:OllamaPort -WarningAction SilentlyContinue -InformationLevel Quiet)) {
        Write-Host "Ollama ne repond pas sur ${script:OllamaHost}:${script:OllamaPort}. Demarre le service Ollama puis reessaie." -ForegroundColor Red
        return
    }

    # 1b. Le port repond, mais est-ce CE modele qui est installe ?
    if (-not (Test-OllamaHasModel -Tag $Model)) {
        Write-Host "Ollama repond mais '$Model' n'apparait pas dans 'ollama list'. 'ollama pull $Model' ou corrige -Model." -ForegroundColor Red
        return
    }

    # 2. Redirection de l'agent vers Ollama (API Anthropic native, sans proxy)
    $env:ANTHROPIC_BASE_URL         = "http://${script:OllamaHost}:${script:OllamaPort}"
    $env:ANTHROPIC_AUTH_TOKEN       = "ollama"            # jeton Bearer attendu par Ollama, pas une cle Anthropic
    $env:ANTHROPIC_MODEL            = $Model
    $env:ANTHROPIC_SMALL_FAST_MODEL = $Model              # taches background -> meme modele

    # 3. Timeouts - modele local lent. Cote client Claude Code (ms)
    $env:API_TIMEOUT_MS             = $script:ClientTimeoutMs

    # 4. Mode 100% offline (coupe telemetrie/auto-update Anthropic)
    $env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"

    # Revue PR #61, finding #1 (reel) : sauvegarde la cle AVANT de la retirer,
    # pour que claude-cloud puisse vraiment la restaurer plutot que de la
    # laisser disparue. $script:ApiKeySaved distingue "jamais appele
    # claude-ollama dans ce shell" de "appele, et il n'y avait pas de cle".
    $script:SavedApiKey = $env:ANTHROPIC_API_KEY
    $script:ApiKeySaved = $true
    Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[LOCAL] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> $Model (local, Ollama direct, sans proxy)" -ForegroundColor Green
    claude
}

function claude-cloud {
    param([string]$SessionName)

    Remove-Item `
        Env:\ANTHROPIC_BASE_URL, `
        Env:\ANTHROPIC_AUTH_TOKEN, `
        Env:\ANTHROPIC_MODEL, `
        Env:\ANTHROPIC_SMALL_FAST_MODEL, `
        Env:\API_TIMEOUT_MS, `
        Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC `
        -ErrorAction SilentlyContinue

    # Restaure la cle que claude-ollama avait retiree (revue PR #61, finding
    # #1). Si claude-ollama n'a jamais tourne dans ce shell, ApiKeySaved
    # n'existe pas et rien n'est touche - un ANTHROPIC_API_KEY deja present
    # pour une AUTRE raison reste intact.
    if ($script:ApiKeySaved) {
        if ($null -ne $script:SavedApiKey) {
            $env:ANTHROPIC_API_KEY = $script:SavedApiKey
        } else {
            Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
        }
        $script:ApiKeySaved = $false
    }

    if ($SessionName) {
        try { $Host.UI.RawUI.WindowTitle = "[CLOUD] $SessionName" } catch { }
    }
    Write-Host "Claude Code -> Anthropic Cloud." -ForegroundColor Yellow
    claude
}

Set-Alias claude-local claude-ollama   # les deux noms marchent
