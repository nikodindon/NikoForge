# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnage : [Semantic Versioning](https://semver.org/lang/fr/).

## [Non publié] — Refonte v3.0 (branche `dev`)

Refonte complète. Analyse et justification : [`docs/REFONTE.md`](docs/REFONTE.md).
Plan d'exécution : [`ROADMAP.md`](ROADMAP.md).

### Corrigé (à venir)

17 défauts identifiés et reproduits sur la v2. Les principaux :

- Parser XML qui tronque silencieusement le contenu généré dès qu'il contient une balise
  de fermeture (`</tool>`, `</param>`, `</tool_calls>`) — écrire un fichier HTML ou
  documenter le format XML suffisait à corrompre le fichier.
- `iteration` jamais remise à zéro : `max_iterations` était un budget de **session**, si bien
  qu'après 20 itérations cumulées l'agent devenait un no-op silencieux (`run()` renvoyait
  une chaîne vide sans aucun message).
- Le modèle recevait une `repr()` Python (`Données: {'stdout': ...}`) au lieu de la sortie
  brute de l'outil.
- `reasoning_content` fusionné dans le contenu final : la réflexion du modèle était stockée
  dans l'historique et renvoyée à chaque tour.
- `edit_file` remplaçait **toutes** les occurrences d'un motif, sans avertissement.
- Aucune borne sur les entrées/sorties : `read_file` sans `offset`/`limit`, `bash` renvoyant
  stdout+stderr complets.
- Compaction non-LLM qui concatène et tronque les messages bruts par découpage de chaîne, et
  ne conserve que les 2 derniers messages — la tâche initiale disparaissait du contexte actif.
- `skills_dir` / `projects_dir` déclarés dans la configuration et documentés, mais lus par
  aucune ligne de code.
- `config.json` obligatoire, absent du dépôt et gitignoré : le projet ne démarrait pas.

### Ajouté

- **Paquet installable** : `console_scripts` (`nikoforge`), `python -m nikoforge`, version
  dynamique lue depuis `nikoforge/__init__.py`.
- `nikoforge doctor` : 10 contrôles d'installation (python, paquet, config, serveur, modèle,
  contexte cohérent avec le serveur, outils, skills, répertoire de travail, stockage) avec un
  remède par échec et un code de sortie exploitable.
- `nikoforge init` : assistant de premier lancement. Détecte le serveur, lit `/v1/models`,
  choisit le modèle et écrit une configuration TOML complète et commentée. Si aucun serveur ne
  répond, il affiche la commande `llama-server` à copier, avec un GGUF local détecté.
- **Configuration TOML** (`~/.config/nikoforge/config.toml`) : entièrement facultative, avec
  précédence `défauts < fichier < environnement < ligne de commande`. 10 variables
  `NIKOFORGE_*`. Une clé ou une section inconnue est refusée avec la liste des clés valides.
- `--version`, `--print-config` (TOML commenté, ré-analysable), `--print-system-prompt`.
- **Pré-vol** : `GET /v1/models` est testé avant la première itération ; serveur absent →
  message clair, commande à lancer, code de sortie 3.
- **Découverte automatique du modèle** : `llm.model` vide ⇒ le nom est lu sur `/v1/models`.
  C'est ce qui permet de démarrer sans aucun fichier de configuration.
- `tests/fake_server.py` : vrai serveur HTTP compatible OpenAI (modèles, streaming SSE,
  `/props`) utilisé par les tests et les démonstrations. Le trajet CLI → pré-vol → HTTP →
  streaming est exercé pour de bon ; seul le modèle est simulé.
- `docs/migration-v2-v3.md` et `docs/prompts.md`.
- Licence MIT, `.editorconfig`, `CHANGELOG.md`.
- `examples/` : les deux projets de démonstration, sortis de la racine.

### Modifié

- `core/` devient le paquet `nikoforge/`. `nikoforge.py` est supprimé.
- `README.md` réécrit en trois sections (Installer / Utiliser / Étendre), avec des sorties de
  commandes réelles recopiées telles quelles.
- `llm.timeout` passe de « pas de limite » (l'attente infinie du bug C10) à 300 secondes ;
  `0` signifie désormais « pas de limite ».
- Le mode interactif devient le mode par défaut ; `-i` est accepté mais sans effet.
- `nikoforge "tâche"` fonctionne toujours, avec un avertissement de dépréciation sur `stderr`.

### Supprimé

- 9 résidus d'exécutions de l'agent (`run.py`, `run.sh`, `run_test.sh`, `test.py`, `test.txt`,
  `xmltest.py`, `bonjour.py`, `hello.py`, `index.html`) : fichiers en racine, cassés ou vides.
- `test_parser.py` et `test_tools.py` : scripts d'affichage sans aucune assertion.
- `requirements.txt` (redondant avec `dependencies` de `pyproject.toml`) et
  `config.example.json` (remplacé par les défauts en dur et `--print-config`).
- La section `paths` de la configuration : `projects_dir`, `logs_dir` et `skills_dir` étaient
  déclarés et documentés mais lus par aucune ligne de code (bug C12).

## [2.0.0] — 2026-05-26

### Ajouté

- Format XML pour les appels d'outils (`<tool_calls>`, `<tool>`, `<param>`), inspiré de
  pi-dev / qwen-code, avec extraction par expression régulière.
- Streaming en temps réel des réponses du modèle.
- System prompt minimaliste (~200 tokens).

## [1.0.0] — MVP

### Ajouté

- Implémentation de base : outils `read_file`, `write_file`, `edit_file`, `bash`, `list_files`.
- Gestion du contexte avec compaction automatique.
- Mode interactif.
- Configuration par fichier JSON.
