---
name: nikoforge
version: 3.0.0
category: software-development
description: "Workflow de refonte et maintenance du projet NikoForge (agent de coding local, vraie mesure sur serveur llama-server, protocole XML natif + CDATA, correction C18, D1 tranchee par mesure)."
---
# NikoForge — workflow de refonte et maintenance

Classe de tache : audit de projet legacy, refonte phasee avec tests reels (vrai serveur llama-server), documentation des bugs (C1-C18), correction du protocole d'appel d'outils natif (machine a etat + CDATA), et suivi de roadmap.

## Procedure (ordre des etapes)

1. **Audit initial** : lire `docs/REFONTE.md` (17/18 bugs documentes), `docs/DECISIONS.md` (D1-D6 proposees), `docs/migration-v2-v3.md`. Creer le suivi dans `ROADMAP.md`.
2. **Mesure du vrai serveur** : lancer `.venv/bin/nikoforge --base-url http://100.91.114.49:8080/v1 doctor`. Verifier `/v1/props` (`chat_template_caps.supports_tools`) et `/v1/models` (`capabilities` — attention : annonce faux `completion` alors que natif marche). Confirmer le mode natif par un vrai appel (test E2E avec `hello.py` ou `tetris.html`).
3. **Phase 3 (coeur fiable)** : re-ecrire `protocol.py` (machine a etat, CDATA, balayage hierarchique), `agent.py` (correction C18 : message assistant conserve `tool_calls`, resultats en `role="tool"`), `context.py` (compaction par le modele, pas de `timestamp` dans le rendu), `llm.py` (streaming, erreurs nommees, reprise), `prompt.py` (engendre depuis `protocol.TOOL_SPECS`).
4. **Tests** : 416 verts (`tests/test_protocol.py` 103, `test_agent_loop.py` 67, `test_config.py` 55, `test_llm.py` 51, `test_cli.py` 46, `test_server.py` 49, `test_context.py` 32, `test_ui.py` 13). `ruff` et `mypy` propres.
5. **Phase 4 (outillage)** : `AGENTS.md` re-ecrit (format XML natif/CData, reference `skills/`), `skills/python-development.md` mis a jour (v3, DECISIONS.md, C18). Registre `@tool` : source unique `protocol.TOOL_SPECS` -> `prompt.py`.
6. **Phase 5 (UX)** : `ui.py` (`render_mode()` plain/rich/json, `SESSION_DIR`, `CHECKPOINT_DIR`, stub `/undo`), `cli.py` (`--stream`, `--json`, `--dry-run`, `--yes` stubs), `session.py` (JSONL), `logs_dir` (`~/.local/state/nikoforge/logs/`).
7. **Phase 6 (qualite et CI)** : `ruff` elargi (`E,W,F,I,UP,B`), `pytest` 416 verts, couverture >70% et badge CI GitHub Actions non atteints (restants documentes dans `ROADMAP.md`).
8. **Phase 7 (publication)** : non atteinte (merge `dev`->`main`, tag `v3.0.0`, release). `dev` reste la branche de travail.

## Commandes concretes

```bash
# Installation
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Tests complets
.venv/bin/python -m pytest -q

# Vrai serveur (test integ)
.venv/bin/nikoforge --base-url http://100.91.114.49:8080/v1 doctor
.venv/bin/nikoforge --base-url http://100.91.114.49:8080/v1 --stream -p "Creer hello.py..."

# Rendu (phase 5)
.venv/bin/nikoforge --plain -p "..." | cat
.venv/bin/nikoforge --base-url ... -p "..."
```

## Decisions trancheres (docs/DECISIONS.md)
- D1 : hybride (detecte sur `/props`, natif si annonce, sinon texte CDATA). Confirme par mesure (vrai serveur `capabilities: ["completion"]` faux, `chat_template_caps.supports_tools: true`).
- D2 : REPL par defaut (`-i` deprecie, sans effet).
- D3 : pas de confinement / sandbox (utilisateur confirme `pas besoin de confinement`).
- D4 : MIT (licence dans `pyproject.toml`).
- D5 : nom `nikoforge` (commande dans `pyproject.toml`).
- D6 : TOML (`config.toml` optionnel, variables env `NIKOFORGE_*`).

## Pitfalls (regles imperatives + mecanisme)

- **Toujours verifier le vrai serveur avant de trancher le protocole natif** (`GET /v1/props` + `/v1/models` ; `capabilities` peut mentir). Mecanisme : le gabarit de chat du serveur peut annoncer `completion` tout en gerant `tools` natif ; sans appel reel, on ne sait pas.
- **C18 (message assistant vide apres outil)** doit etre corrige en conservant le message assistant avec ses `tool_calls` et en renvoyant le resultat en `role="tool"`. Mecanisme : sans cela, le modele ne lie pas le resultat a l'appel, et rappelle l'outil indefiniment (boucle infinie, budget epuise, exit 1).
- **Le parser regex v2 tronquait le contenu sur `</tool>`** : remplacer par machine a etat (balayage hierarchique, CDATA inclus). Mecanisme : chaque balise est consommee en entier ; `]]>` dans le contenu ne termine pas le CDATA.
- **Le faux serveur (`tests/fake_server.py`) ne reproduit pas la validation du gabarit de chat** ; certains bugs (C18) ne sont visibles que sur un vrai `llama-server`. Mecanisme : le faux serveur n'a pas le gabarit natif qui valide `tool_calls` / `role`.
- **La compaction (`context.py`) doit garder le message assistant porteur de `tool_calls` lie a ses resultats `tool`** ; sinon le gabarit du serveur echoue. Mecanisme : un `tool` orphelin (sans `tool_call_id` lie) fait echouer le rendu natif.
- **Le `cli.py` subparser `doctor`/`init` ecrasait `--base-url`** (`argument_default=SUPPRESS` requis). Mecanisme : argparse recree un namespace pour chaque sous-commande et recopie ses valeurs par defaut dans le parent, ecrasant la valeur fournie.
- **Le mode `--plain` doit supprimer tout emoji et ANSI** (pour pipes et CI). Mecanisme : le rendu `rich` utilise des barres de progression (`█/░`), des emojis (`⚕`, `📋`), et des codes couleur implicites ; `plain` ne doit conserver que le texte brut.

## References
- `docs/DECISIONS.md` (D1-D6)
- `docs/REFONTE.md` (C1-C18, audit initial)
- `docs/ROADMAP.md` (phases 0-7, suivi d'avancement)
- `docs/migration-v2-v3.md`
- `tests/fake_server.py` (faux serveur OpenAI-compatible, outils fragmentes, raisonnement)
- `tests/test_protocol.py` (103 tests, encodeur/decodeur)
- `tests/test_agent_loop.py` (tests natifs, structure messages)
