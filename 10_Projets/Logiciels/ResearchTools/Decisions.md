# Résumé des Décisions d'Architecture — ResearchTools

## 2026-09-25 — Agent + Compétence + Commande pour le CV narratif FRQ

**Quoi:**
Construit un trio complet pour la rédaction du CV descriptif FRQ (conformément à la structure identique du CV commun tri-organismes CIRC/CRSNG/CRSH : trois sections, jusqu'à 10 articles en section 2, limite de 6 pages FR / 5 pages EN) :
- Compétence `.claude/skills/narrative-cv/` (scripts : cv_common.py, cv_inventory.py, cv_select.py, cv_build.py; fichier de données contribution_types.json; 61 tests unitaires hors ligne, tous passants)
- Agent `.claude/agents/narrative-cv-writer.md`
- Commande `.claude/commands/cv.md` (`/cv`)

**Pourquoi:**
Permet la rédaction automatisée et cohérente du CV narratif pour les appels FRQ, en réutilisant l'identité du chercheur et l'inventaire des contributions existants. Le choix du modèle d'inventaire durable (YAML) dans le dossier externe du chercheur offre une maintenance incrémentale à travers les cycles de subventions, évitant une reconstruction entière pour chaque concours.

**Conception clé:**
Un inventaire des contributions durable (YAML) demeure dans le dossier externe du projet du chercheur, rafraîchi graduellement à travers les cycles de subvention via Scopus (deux étapes AU-ID, même motif que cover-paper Artefact 3) + extract-contributions, et reclassé par compétition selon le chevauchement des mots-clés (cv_select.py) plutôt que reconstruit de zéro chaque fois. L'utilisateur a explicitement choisi cette approche par rapport à une alternative sans état quand interrogé (choix enregistré dans la réponse de dispatch).

**Conséquences:**
- Inscription/ajout de schéma : `profiles/<active>.yaml` a gagné une nouvelle clé `cv.project_dir` (emplacement du dossier du projet CV externe) aux côtés du bloc `author` réutilisé pour l'identité d'en-tête CV ; les deux suivent le motif sans alternative-refuser-défaut (R8) déjà utilisé par letter_identity.py de recommendation-letter. `profiles/engineering.yaml`, `profiles/_template.yaml` et `profiles/README.md` ont été mis à jour pour correspondre.
- Documentation mise à jour : table de routage `.claude/CLAUDE.md`, README.md (tables compétence/agent/commande + sous-section narrative-cv + arborescence File-Locations), Architecture.md (nœuds/arêtes graphe mermaid + note matrice), `.claude/rules/workflows.md`, `.claude/rules/testing.md`.
- `install.ps1` et `install-junctions.ps1` s'exécutent avec succès ; suite hors ligne complète verte (89 passés, 0 échoués, 1 non exécutés pour une dépendance optionnelle manquante préexistante) ; `.rt-green.json` restauré.

**Problèmes découverts (non corrigés, à examiner ultérieurement):**
1. pip-audit a trouvé 3 nouveaux CVE (PYSEC-2026-3910/3911/3913) contre pypdf 6.15.0 tout en pinant le requirements.txt de cette compétence, corrigé en pinant 6.16.1 ici — mais la compétence paper2talk préexistante pinne toujours la vulnérable 6.15.0 et n'a pas été touchée.
2. `install-junctions.ps1` a rapporté 18 fichiers d'agent préexistants sous `~/.claude/agents/` (abstract-writer, cover-paper, scopus-researcher, thesis-auditor, et 14 autres) qui sont des FICHIERS RÉELS plutôt que des liens vers ce dépôt, ce qui signifie que ces agents ne chargent PAS le contenu de repo actuel dans les sessions Claude Code sur cette machine — narrative-cv-writer lui-même s'est lié correctement en tant que nouveau lien physique puisque les symlinks Developer Mode ne sont pas disponibles, mais les 18 plus anciens sont occultés et nécessitent une suppression manuelle pour être reconnectés.
