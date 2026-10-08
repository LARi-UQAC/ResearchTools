#Requires -Version 5.1
<#
.SYNOPSIS
    Bascule Claude Code lui-meme entre un modele Ollama local (direct, sans
    proxy) et le cloud Anthropic.

.DESCRIPTION
    Deux fonctions dot-sourcees : claude-ollama (alias claude-local) redirige
    Claude Code vers un modele Ollama servi en local, claude-cloud efface la
    redirection et revient au cloud Anthropic.

    Ceci est INDEPENDANT du pont local-writer/local-coder de ce depot
    (.claude/skills/loop-engineer/scripts/ollama_bridge.py, model_resolver.py) :
    ce script redirige la session Claude Code elle-meme, pas les agents de ce
    depot, et ne passe donc pas par le resolver. R0/R2 (pas de tag ni de valeur
    numerique en dur sans provenance) ne s'appliquent pas de la meme facon ici
    puisqu'il n'y a pas de mesure GPU a tenir a jour : le modele par defaut
    ci-dessous est un choix personnel de l'operateur, modifiable par -Model ou
    en changeant $script:DefaultLocalModel.

    MAJ 2026-10-08 : Ollama expose nativement l'API Anthropic Messages
    (/v1/messages) depuis la mise a jour du 16 janvier 2026 (>= v0.14,
    generalisee v0.15+). Le proxy LiteLLM (Anthropic -> OpenAI -> Ollama)
    n'est plus necessaire : Claude Code pointe directement sur
    http://localhost:11434.

.NOTES
    Une copie geree a la main peut exister dans le profil utilisateur de
    l'operateur (hors depot) ; cette copie versionnee dans ResearchTools en
    est la source de reference.

.EXAMPLE
    . .\scripts\local\claude-switch.ps1
    claude-local
    claude-cloud
#>

# Modele Ollama par defaut pour la bascule locale. Choix personnel de
# l'operateur, pas une mesure du pont local-writer/local-coder (voir
# .claude/local-model-config.json pour les tags mesures pour CE pont) : ce
# tag-ci a son propre Modelfile (hors depot), mesure separement pour l'usage
# /auditthesis local - num_ctx 262144, num_thread 14, mesure le 2026-10-08 :
# 0 des 66 layers sur GPU, ~2.4 tok/s, forte pagination. Fenetre maximale
# choisie deliberement, pas la vitesse.
$script:DefaultLocalModel = "qwen3.8-maxctx:latest"

function claude-ollama {
    param(
        [string]$Model = $script:DefaultLocalModel
    )

    # 1. Verifie qu'Ollama repond avant de rediriger l'agent dessus (pas de
    #    demarrage silencieux : un echec ici doit arreter la bascule, pas
    #    lancer Claude Code contre un port mort).
    if (-not (Test-NetConnection -ComputerName localhost -Port 11434 -WarningAction SilentlyContinue -InformationLevel Quiet)) {
        Write-Host "Ollama ne repond pas sur :11434. Demarre le service Ollama puis reessaie." -ForegroundColor Red
        return
    }

    # 2. Redirection de l'agent vers Ollama (API Anthropic native, sans proxy)
    $env:ANTHROPIC_BASE_URL         = "http://localhost:11434"
    $env:ANTHROPIC_AUTH_TOKEN       = "ollama"            # jeton Bearer attendu par Ollama, pas une cle Anthropic
    $env:ANTHROPIC_MODEL            = $Model
    $env:ANTHROPIC_SMALL_FAST_MODEL = $Model              # taches background -> meme modele

    # 3. Timeouts - modele local lent. Cote client Claude Code (ms)
    $env:API_TIMEOUT_MS             = "600000"            # 10 min avant abandon requete

    # 4. Mode 100% offline (coupe telemetrie/auto-update Anthropic)
    $env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"

    Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
    Write-Host "Claude Code -> $Model (local, Ollama direct, sans proxy)" -ForegroundColor Green
    claude
}

function claude-cloud {
    Remove-Item `
        Env:\ANTHROPIC_BASE_URL, `
        Env:\ANTHROPIC_AUTH_TOKEN, `
        Env:\ANTHROPIC_MODEL, `
        Env:\ANTHROPIC_SMALL_FAST_MODEL, `
        Env:\API_TIMEOUT_MS, `
        Env:\CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC `
        -ErrorAction SilentlyContinue
    Write-Host "Claude Code -> Anthropic Cloud." -ForegroundColor Yellow
    claude
}

Set-Alias claude-local claude-ollama   # les deux noms marchent
