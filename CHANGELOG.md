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

- `pyproject.toml` (PEP 621) avec le jeu d'outils de développement (`pytest`, `ruff`, `mypy`).
- Suite de tests `tests/` : filet de sécurité qui capture le comportement réel de la v2.
  Les tests marqués `known_issue` documentent un bug identifié et seront inversés en phase 3.
- `LICENSE` (MIT), `.editorconfig`, `CHANGELOG.md`.
- `docs/DECISIONS.md` : journal des arbitrages d'architecture.
- `examples/` : les projets de démonstration produits par l'agent, sortis de la racine.

### Modifié

- `README.md` : bandeau signalant la refonte en cours sur `dev`.

### Supprimé

- 9 résidus d'exécutions de l'agent (`run.py`, `run.sh`, `run_test.sh`, `test.py`, `test.txt`,
  `xmltest.py`, `bonjour.py`, `hello.py`, `index.html`) : fichiers en racine, cassés ou vides.
- `test_parser.py` et `test_tools.py` : scripts d'affichage sans aucune assertion.

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
