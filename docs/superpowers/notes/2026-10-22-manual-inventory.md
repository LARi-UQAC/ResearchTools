# Inventaire ResearchTools et couverture du manuel (docs/manual/)

Date: 2026-10-22. Branche: `docs/manual-sync-inventory`. Base: `main` au commit ab86944.

Méthode: les éléments sont listés depuis le dépôt (dossiers `.claude/agents`, `.claude/skills`,
`.claude/commands`, `.claude/hooks`, `.claude/settings.template.json`, `mirror-policy.json`,
`scripts/`, `.github/workflows/`, `deploy/`). La couverture est mesurée en cherchant chaque nom
dans `docs/manual/*.md` puis en lisant les passages trouvés. Limite: une cellule `m` ou `!` est
un constat vérifié, une cellule `✓` veut dire "présent et sans défaut trouvé", pas "chaque phrase
du chapitre a été comparée au code".

Légende de la colonne Statut:

| Code | Sens |
|---|---|
| ✓ | présent dans le manuel |
| X | absent du manuel |
| ! | bloquant: le manuel affirme quelque chose de faux qui fait échouer ou induit en erreur |
| m | présent, mais un détail est manquant ou périmé |

La colonne Corrigé vaut `☐` avant la correction et `☑` après. Toutes les cases sont à `☑` à la fin de la session du 2026-10-22.

## 1. Ordre des chapitres

Ordre actuel (illogique: Skills au 04, Commands au 08, Agents au 10, File locations au 11):

| Actuel | Titre |
|---|---|
| 00 | Purpose & overview |
| 01 | Installation |
| 02 | Profiles & environment |
| 03 | Token management |
| 04 | Skills |
| 05 | Security audit |
| 06 | Aider nightly pipeline |
| 07 | rt-observe & dashboard |
| 08 | Commands |
| 09 | ThesisTracker integration |
| 10 | Agents |
| 11 | File locations |
| 12 | Local coding and the cloud |

Ordre proposé et appliqué le 2026-10-22 (parcours du lecteur: comprendre, installer, configurer, utiliser, gouverner,
exploiter, référence). Les chapitres marqués NEW comblent un manque de la section 2.

| Proposé | Titre | Origine | Raison de la place |
|---|---|---|---|
| 00 | Purpose & overview | 00 | inchangé |
| 01 | Installation | 01 | inchangé |
| 02 | Profiles & environment | 02 | inchangé |
| 03 | Token management | 03 | inchangé, hygiène de session avant tout travail |
| 04 | Commands | 08 | ce que l'utilisateur tape en premier |
| 05 | Agents | 10 | ce que les commandes appellent |
| 06 | Skills | 04 | ce que les agents réutilisent, plus les deux mémoires |
| 07 | Hooks and guards | NEW | ce qui s'exécute tout seul autour des outils |
| 08 | Rules and conventions | NEW | R0 à R38 et les cinq fichiers `.claude/rules/` |
| 09 | Harnesses and mirrors | NEW (tiré de 10 et 01) | Claude Code, Copilot, OpenCode, Continue, Aider, Codex |
| 10 | Local coding and the cloud | 12 | choix de l'exécuteur, plans, bornes |
| 11 | Aider nightly pipeline | 06 | une des voies du chapitre 10 |
| 12 | rt-observe & dashboard | 07 | observer ce qui précède |
| 13 | Security audit and guards | 05 | garde de données personnelles, revue PR, SkillSpector |
| 14 | ThesisTracker integration | 09 | frontière avec le dépôt frère |
| 15 | Maintenance, checks and CI | NEW | `run-all-checks`, `finish-branch`, `verify-*`, `mkdocs gh-deploy`, workflows |
| 16 | File locations | 11 | référence |
| 17 | PCB design | NEW, placeholder | demandé par le propriétaire le 2026-10-22, à rédiger la semaine du 2026-10-26 |
| 18 | 3D CAD design | NEW, placeholder | idem |

Renommer les fichiers touche 30 fichiers (156 occurrences): `mkdocs.yml`, `README.md`,
`docs/index.md`, tous les chapitres, deux fichiers de règles, deux instructions Copilot
générées, et quatre tests (`test_manual_local_coding.py`, `test_local_coding_docs.py`,
`test_review_bounds_rule.py`, `test_skill_first_rule.py`). `IMPROVEMENTS.md` (journal
historique) reste tel quel.

## 2. Inventaire et couverture

### 2.1 Agents (21)

Chapitre actuel: 10 Agents. Tous ont une ligne dans le tableau du chapitre.

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| abstract-writer | ✓ | | ☑ |
| authoring-loop | ✓ | | ☑ |
| bib-cleaner | ✓ | | ☑ |
| cover-paper | ✓ | | ☑ |
| latex-writer | ✓ | | ☑ |
| litreview-updater | ✓ | | ☑ |
| local-coder | m | la ligne décrit encore "code against a spec"; l'agent exécute UN plan entier (`PLAN:`, R38, garde de dispatch) | ☑ |
| local-writer | m | la ligne ignore son rôle de gardien des deux mémoires (coffre et graphe) | ☑ |
| narrative-cv-writer | ✓ | | ☑ |
| paper-auditor | ✓ | | ☑ |
| professor-expertise-finder | ✓ | | ☑ |
| reviewer-response | ✓ | | ☑ |
| scopus-auditor | ✓ | | ☑ |
| scopus-researcher | ✓ | | ☑ |
| submit-checker | ✓ | | ☑ |
| talk-builder | ✓ | | ☑ |
| thesis-auditor | ✓ | | ☑ |
| thesis-proposal-auditor | ✓ | | ☑ |
| thesis-to-paper | ✓ | | ☑ |
| word-to-latex | ✓ | | ☑ |
| wp-portfolio-agent | ✓ | | ☑ |
| Comptes du chapitre ("Twenty ship") | m | 21 agents | ☑ |
| Section "Loop engineering": contrat d'options `--loop --budget` | ! | `--loop` n'est pas câblé, le chapitre 08 le dit et celui-ci le contredit | ☑ |

### 2.2 Skills (25 dans le dépôt, plus graphify externe)

Chapitre actuel: 04 Skills.

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| aider-setup | ✓ | | ☑ |
| deliberation | ✓ | | ☑ |
| drawio2tikz | ! | point d'entrée `/drawio2tikz` inexistant, il n'y a pas de fichier commande | ☑ |
| extract-contributions | ✓ | | ☑ |
| extract-futureworks | ✓ | | ☑ |
| extract-paper-idea | ✓ | | ☑ |
| extract-statistic | ✓ | | ☑ |
| form-service | m | colonne point d'entrée = "Yes"; la commande est `/fetchform` | ☑ |
| geolocalisation | ✓ | | ☑ |
| latex-hygiene | ✓ | | ☑ |
| loop-engineer | ✓ | bloc "local coding contract" présent | ☑ |
| narrative-cv | ✓ | | ☑ |
| obsidian-cli | ✓ | | ☑ |
| opt-local-stt-vram | ✓ | | ☑ |
| opt-local-vram-llm | ✓ | | ☑ |
| paper2talk | ✓ | | ☑ |
| pdf2md | ✓ | | ☑ |
| professor-expertise-finder | ✓ | | ☑ |
| recommendation-letter | ✓ | | ☑ |
| rt-observe | m | aucune ligne dans le tableau des skills (décrit au chapitre 07 seulement) | ☑ |
| scholar-evaluation | ✓ | | ☑ |
| scientific-writing | ✓ | | ☑ |
| scopus | ✓ | | ☑ |
| word2latex | ✓ | | ☑ |
| wp-portfolio-sync | m | section dédiée, mais aucune ligne dans le tableau | ☑ |
| graphify (externe) | ✓ | | ☑ |
| Phrase d'ouverture "Fifteen ship" | m | 25 skills | ☑ |
| Liste "In this chapter" | m | n'ancre que 11 skills | ☑ |

### 2.3 Commandes (32)

Chapitre actuel: 08 Commands. Les 32 ont une ligne dans le tableau.

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| /abstract | ✓ | | ☑ |
| /auditpaper | ✓ | | ☑ |
| /auditreview | ✓ | | ☑ |
| /auditthesis | ✓ | | ☑ |
| /bibclean | ✓ | | ☑ |
| /concis | ✓ | | ☑ |
| /ctx | ✓ | | ☑ |
| /cv | ✓ | | ☑ |
| /doc | ✓ | | ☑ |
| /expertfinder | ✓ | | ☑ |
| /fetchform | ✓ | | ☑ |
| /focus | ✓ | | ☑ |
| /geolocalisation | ✓ | | ☑ |
| /latex | ✓ | | ☑ |
| /litreview | ✓ | | ☑ |
| /litupdate | ✓ | | ☑ |
| /loopdev | ✓ | | ☑ |
| /opt-local-stt-vram | ✓ | | ☑ |
| /opt-local-vram-llm | ✓ | | ☑ |
| /pdf2md | ✓ | | ☑ |
| /portfolio | ✓ | | ☑ |
| /recommendation-letter | ✓ | | ☑ |
| /ref | ✓ | | ☑ |
| /replyreviewer | ✓ | | ☑ |
| /rt-dashboard | ✓ | | ☑ |
| /slim | ✓ | | ☑ |
| /submitcheck | ✓ | | ☑ |
| /talk | ✓ | | ☑ |
| /test | ✓ | | ☑ |
| /texcheck | ✓ | | ☑ |
| /tikz | ✓ | | ☑ |
| /word2latex | ✓ | | ☑ |
| Chapitre 02: `/litreview-updater` | m | la commande est `/litupdate` | ☑ |
| Chapitre 00 "31 commands" | m | 32 commandes | ☑ |

### 2.4 Hooks (session Claude Code, déclarés dans `settings.template.json`)

Aucun chapitre ne les décrit. Ils sont cités en passant (prérequis, sécurité, tableau de bord).

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| Chapitre "Hooks and guards" | X | à créer (07 proposé) | ☑ |
| betterleaks-hook.py (PreToolUse, secrets) | m | cité comme prérequis, rôle non décrit | ☑ |
| vault-access-guard.py (PreToolUse, coffre et graphe) | m | cité une fois | ☑ |
| askuserquestion-clarity.py (PreToolUse, R25) | X | | ☑ |
| worktree-link-guard.py (PreToolUse, R37) | ✓ | chapitre 05 | ☑ |
| review-loop-guard.py (PreToolUse, R35) | ✓ | chapitres 08 et 12 | ☑ |
| local-coder-dispatch-guard.py (PreToolUse, R38) | ✓ | chapitre 12 | ☑ |
| prompt-injection-defender.py (PostToolUse) | m | cité une fois | ☑ |
| pip-audit-hook.py (PostToolUse) | m | l'outil pip-audit est décrit, pas le hook | ☑ |
| caveman-activate.js (SessionStart) | m | cité comme prérequis Node | ☑ |
| caveman-mode-tracker.js (UserPromptSubmit) | X | | ☑ |
| auto-sync git (SessionStart, en ligne) | m | | ☑ |
| rtk-active et session-status (SessionStart, en ligne) | X | | ☑ |
| session-hooks-inventory.py (SessionStart) | X | | ☑ |
| obsidian-outbox-flush.py (SessionStart et SessionEnd) | ✓ | chapitre 10 | ☑ |
| rt-inbox-deliver.py (UserPromptSubmit) | X | | ☑ |
| memory-upkeep (Stop, en ligne) | m | cité une fois | ☑ |
| Variables `env` du gabarit (`CLAUDE_CODE_GIT_BASH_PATH`, `ENABLE_STOP_REVIEW`, `GRAPHIFY_*`) | m | `GRAPHIFY_*` seulement | ☑ |
| Hooks git globaux pre-commit et pre-push (garde de données personnelles) | ✓ | chapitres 01 et 05 | ☑ |

### 2.5 Règles et conventions

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| Chapitre "Rules and conventions" | X | à créer (08 proposé) | ☑ |
| `.claude/rules/code-style.md` (R0 à R19, R27) | X | | ☑ |
| `.claude/rules/preferences.md` (R14, R15, R22, R23, R25, R28) | X | | ☑ |
| `.claude/rules/security.md` (R24) | m | privacy guard décrit au chapitre 05 | ☑ |
| `.claude/rules/testing.md` (R20, R21, R34) | m | cité comme renvoi, jamais résumé | ☑ |
| `.claude/rules/workflows.md` (R26, R29 à R33, R35 à R38) | m | R35 à R38 au chapitre 12, R36 au chapitre 04 | ☑ |
| R30 (Issue et carte avant PR), R31 (docs avant merge), R33 (docs publiques) | X | | ☑ |
| R32 (arbre partagé) | m | cité deux fois | ☑ |
| Profils `engineering`, `cosmetic`, `_template` | ✓ | chapitre 02 | ☑ |

### 2.6 Harnais et miroirs

Chapitre actuel: 10 Agents (section "Using the agents outside Claude Code") et 01 (Step 4).

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| Chapitre "Harnesses and mirrors" | X | à créer (09 proposé) | ☑ |
| Claude Code (natif, `.claude/`) | ✓ | | ☑ |
| GitHub Copilot: agents `.github/agents/` | m | "five large agents ship as stubs", le décompte mesuré en compte sept | ☑ |
| GitHub Copilot: invites `.github/prompts/` | m | "13 prompt files", il y en a 28 | ☑ |
| GitHub Copilot: règles `.github/instructions/` et `copilot-instructions.md` | ✓ | | ☑ |
| GitHub Copilot CLI `~/.copilot/agents/` (`-Personal`) | ✓ | | ☑ |
| Profil utilisateur VS Code (invites et instructions, `-Personal`) | m | une phrase, pas de ligne dans le tableau | ☑ |
| OpenCode `.opencode/agent/` | ✓ | | ☑ |
| Continue `.continue/rules/` | ✓ | | ☑ |
| Aider `CONVENTIONS.md` | ✓ | | ☑ |
| Aider `aider-setup/config/rules.md` (généré) | m | chapitre 06 seulement | ☑ |
| Lecteurs `AGENTS.md` (Codex, Hermes, OpenHuman) | ✓ | | ☑ |
| Codex skills `.agents/skills/` et `AGENTS.md` imbriqué | ✓ | | ☑ |
| `mirror-policy.json` (intention des miroirs) | X | | ☑ |
| Adaptateurs de session (claude_code, copilot_chat, aider) | m | adaptateur aider au chapitre 07, copilot_chat nulle part | ☑ |
| Table "Tool / Generated target" du chapitre 10 | m | ajouter VS Code utilisateur et aider-setup | ☑ |

### 2.7 Installation, maintenance et CI

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| setup.ps1, install.ps1, install-junctions.ps1 | ✓ | chapitre 01 | ☑ |
| `setup.ps1 -Update` et `scripts/lib/rt-update.ps1` | ✓ | chapitre 01 | ☑ |
| `scripts/local/claude-switch.ps1` | ✓ | chapitre 03 | ☑ |
| `scripts/test/run-offline-tests.ps1` | ✓ | chapitre 01 | ☑ |
| `scripts/test/run-all-checks.ps1` | ✓ | chapitre 01 | ☑ |
| `scripts/test/finish-branch.ps1` | m | trois mentions, aucune section | ☑ |
| `scripts/test/verify-*.ps1` (10 vérificateurs) | m | cités en bloc, aucun listé | ☑ |
| `scripts/audit/check-deployment.ps1` | ✓ | chapitre 01 | ☑ |
| `scripts/audit/check-claude-template.ps1` | X | | ☑ |
| `scripts/audit/check-graph-health.ps1` | m | réservé à `local-writer`, deux mentions | ☑ |
| `scripts/docs/mkdocs_hooks.py` et `mkdocs gh-deploy` | X | aucune procédure de publication du site | ☑ |
| Workflow `privacy-scan.yml` | ✓ | chapitre 05 | ☑ |
| Workflow `review.yml` | ✓ | chapitre 05 | ☑ |
| `deploy/form-service/` (API HTTP) | ✓ | chapitres 04 et 09 | ☑ |
| `deploy/` compose, Caddyfile, initdb | X | | ☑ |
| Chapitre "Maintenance, checks and CI" | X | à créer (15 proposé) | ☑ |

### 2.8 Services, mémoires, variables d'environnement

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| Coffre Obsidian et sortie (outbox) | ✓ | chapitres 04 et 10 | ☑ |
| Graphe graphify | ✓ | chapitre 04 | ☑ |
| Démon du coffre (`vault_daemon.py`, autostart) | ✓ | chapitre 01 | ☑ |
| Tableau de bord rt-observe | ✓ | chapitre 07 | ☑ |
| Panneau vocal | ✓ | chapitre 07 | ☑ |
| Variable `GEMINI_API_KEY`, modèle "Gemini 2.0 Flash" | ! | ce modèle est retiré, le skill n'en nomme plus aucun (`auto`) | ☑ |
| Variable `GITHUB_TOKEN` "GPT-4o via GitHub Models" | ! | GitHub Models est retiré depuis 2026-07-30; la voie Copilot lit `COPILOT_TOKEN` ou `GH_OAUTH_TOKEN` | ☑ |
| `COPILOT_TOKEN`, `GH_OAUTH_TOKEN` | X | | ☑ |
| `OBSIDIAN_VAULT`, `PROFESSOR_EXPERTISE_DATA`, `AUGUREAI_API_KEY` | m | dispersés, absents du tableau du chapitre 02 | ☑ |
| `RT_PG_PASSWORD`, `RT_OO_USER`, `RT_OO_PASSWORD` (journal optionnel) | X | | ☑ |

### 2.9 Autres affirmations du manuel à corriger

| Élément | Statut | Note | Corrigé |
|---|---|---|---|
| Chapitre 05: "All eight skills ... scanned 2026-06-18" | ! | 25 skills existent, seuls 8 ont été scannés; le titre laisse croire à un audit de tout | ☑ |
| Chapitre 00: "design the code, PCB and 3D CAD" | ! | aucun skill, agent ni commande du dépôt ne traite PCB ou CAO 3D | ☑ |
| Chapitre 00: comptes "24 skills, 20 agents, 31 commands" | m | 25, 21, 32 | ☑ |
| Chapitre 11: arbre de fichiers | m | se déclare non réconcilié (manque rt-observe, obsidian-cli, pdf2md, hooks, scripts, deploy) | ☑ |
| Chapitre 07: bascule vers `docs/rt-observe.md` | ✓ | | ☑ |
| Chapitre 09 (ThesisTracker), chapitre 06 (aider), chapitre 12 (local coding) | ✓ | relus par PR #84 et #86, aucun défaut trouvé | ☑ |

## 3. Résultat des corrections (2026-10-22)

Décisions du propriétaire: ordre proposé avec fichiers renommés, nouveaux chapitres PCB et CAO 3D
créés vides, SkillSpector relancé sur les 25 skills, les trois autres bloquants corrigés par
retrait de texte faux.

| Bloquant | Correction |
|---|---|
| Chapitre 05 "All eight skills" | Scan relancé sur les 25 skills, résultat dans le chapitre 13, chapitre renommé Security audit and guards |
| Chapitre 00 PCB et CAO 3D | Phrase limitée à ce que le dépôt livre, chapitres 17 et 18 créés comme placeholders, carte de `docs/index.md` corrigée |
| Chapitre 10 `--loop --budget` | Contrat d'options retiré, renvoi aux chapitres 04 et 10 |
| Chapitre 04 `/drawio2tikz` | Entrée remplacée par "le skill, aucune commande" |
| Chapitre 02 Gemini 2.0 Flash et `GITHUB_TOKEN` | Table réécrite d'après le SKILL.md de deliberation |

Constats du scan à traiter hors de cette session (voir le chapitre 13): déclaration de permissions
absente (`LP3`) dans neuf skills, avis `pypdf` 6.19.0 (corrigé en 6.21.1) dans `form-service`,
`narrative-cv` et `paper2talk`, avis `pillow` 12.3.0 (corrigé en 13.0.0) dans `extract-statistic`
et `pdf2md`, avis `docling` 2.103.0 dans `extract-statistic`, `claude-agent-sdk` non épinglé dans
`loop-engineer`.

Vérifications faites: les suites `test_manual_local_coding`, `test_local_coding_docs`,
`test_review_bounds_rule`, `test_skill_first_rule`, `test_plan_contract_rule`,
`test_memory_triggers`, `test_graph_routing` et `test_mkdocs_links` passent, `mkdocs build --strict`
ne donne aucun avertissement, et `install.ps1 -Profile engineering` ne change aucun miroir de plus
que les deux fichiers de règles déjà corrigés. La suite complète `run-offline-tests.ps1` n'a pas
été lancée.
