# Migration v2 → v3

La v3 est une refonte des points d'entrée et de la configuration. Le cœur — boucle de
l'agent, outils, gestion du contexte — produit le même comportement qu'en v2 pour l'instant ;
c'est la phase 3 qui le corrigera. Ce qui change ici, c'est **comment on installe et on
lance**.

## En résumé

| v2 | v3 |
|---|---|
| `git clone` + venv + `pip install -r requirements.txt` | `uv tool install` / `pipx install` |
| `python nikoforge.py "tâche"` depuis le dépôt | `nikoforge -p "tâche"`, depuis n'importe où |
| `python nikoforge.py -i` | `nikoforge` (le REPL est le défaut) |
| `config.json` obligatoire | aucun fichier nécessaire ; TOML facultatif |
| `config.example.json` à copier à la main | `nikoforge init` ou `nikoforge --print-config` |
| version `v2.0` en dur dans l'interface | `nikoforge --version`, source unique |
| aucun code de sortie exploitable | 0 / 1 / 2 / 3 (voir le README) |

## Commandes

```bash
# v2
python nikoforge.py "analyse les logs"
python nikoforge.py --interactive
python nikoforge.py "tâche" --config autre.json
python nikoforge.py "tâche" --save-context session.json

# v3
nikoforge -p "analyse les logs"
nikoforge
nikoforge --config autre.toml -p "tâche"
# (sessions persistantes : phase 5)
```

`python nikoforge.py` n'existe plus : `nikoforge.py` a été remplacé par le paquet
`nikoforge/` (pour qu'il soit installable). L'équivalent sans installation est
`python -m nikoforge`.

La forme `nikoforge "tâche"` (sans `-p`) **fonctionne toujours**, avec un avertissement sur
`stderr`. Elle est dépréciée et sera retirée.

`-i` / `--interactive` est accepté mais sans effet : le mode interactif est désormais le
comportement par défaut, comme dans les autres agents en ligne de commande.

## Configuration

`config.json` devient `config.toml`, à `~/.config/nikoforge/config.toml` (surchargé par
`$NIKOFORGE_CONFIG` ou `--config`). Le fichier est **facultatif** : toutes les valeurs ont une
valeur par défaut dans le programme.

Les clés `llm.*`, `context.*` et `agent.*` gardent le même nom. Deux différences :

- **`paths.*` disparaît.** `projects_dir`, `logs_dir` et `skills_dir` étaient déclarés dans la
  configuration de la v2 et documentés, mais lus par **aucune ligne de code** (bug C12). Les
  chemins sont désormais dérivés : `~/.config/nikoforge`, `~/.local/share/nikoforge` (données),
  `~/.local/state/nikoforge` (journaux), en respectant `XDG_*`.
- **`llm.timeout` valait `null` par défaut** (attente infinie, bug C10). Il vaut maintenant
  `300.0` secondes, et `0` signifie « pas de limite » — TOML n'ayant pas de valeur nulle,
  c'est la seule façon de l'exprimer dans le fichier.

Traduction mécanique d'un `config.json` de la v2 :

```json
{
  "llm":     {"base_url": "http://localhost:8080/v1", "model": "mon.gguf",
              "api_key": "sk-dummy", "temperature": 0.7, "max_tokens": 8192, "timeout": null},
  "context": {"max_tokens": 32000, "compaction_threshold": 0.8, "summary_tokens": 1000},
  "paths":   {"projects_dir": "projects", "logs_dir": "logs", "skills_dir": "skills"},
  "agent":   {"max_iterations": 20, "tool_timeout": 600}
}
```

```toml
[llm]
base_url = "http://localhost:8080/v1"
model = "mon.gguf"
api_key = "sk-dummy"
temperature = 0.7
max_tokens = 8192
timeout = 0.0        # v2 : null = pas de limite

[context]
max_tokens = 32000
compaction_threshold = 0.8
summary_tokens = 1000

[agent]
max_iterations = 20
tool_timeout = 600

# [paths] n'existe plus
```

Une clé inconnue fait maintenant **échouer** le démarrage avec la liste des clés valides,
au lieu d'être ignorée en silence.

## Ce qui a disparu du dépôt

| Supprimé | Raison |
|---|---|
| `nikoforge.py` | remplacé par le paquet `nikoforge/` + `console_scripts` |
| `config.json` / `config.example.json` | défauts en dur + `nikoforge init` + `--print-config` |
| `requirements.txt` | remplacé par `dependencies` de `pyproject.toml` (une seule source) |
| `run.py`, `run.sh`, `run_test.sh` | résidus d'exécutions de l'agent, cassés ou vides |
| `test.py`, `test.txt`, `xmltest.py`, `bonjour.py`, `hello.py`, `index.html` | résidus |
| `test_parser.py`, `test_tools.py` | scripts d'affichage sans assertions → `tests/` |
| `core/` | renommé `nikoforge/` (paquet installable) |
| `calculatrice/`, `asteroid_dodge/` | déplacés dans `examples/` |

## Variables d'environnement (nouvelles)

`NIKOFORGE_BASE_URL`, `NIKOFORGE_MODEL`, `NIKOFORGE_API_KEY`, `NIKOFORGE_TEMPERATURE`,
`NIKOFORGE_MAX_TOKENS`, `NIKOFORGE_TIMEOUT`, `NIKOFORGE_CONTEXT`, `NIKOFORGE_MAX_ITERATIONS`,
`NIKOFORGE_TOOL_TIMEOUT`, `NIKOFORGE_CONFIG`.

Précédence : défauts < fichier TOML < variables d'environnement < arguments CLI.

## À savoir

- Un serveur injoignable n'est plus découvert au milieu de la première itération : un
  **pré-vol** teste `GET /v1/models` avant de commencer et affiche la commande à lancer
  (correctif B2). Le code de sortie est alors `3`.
- Le nom du modèle est **découvert automatiquement** si `llm.model` est vide. C'est ce qui
  permet de démarrer sans aucune configuration.
- `nikoforge doctor` remplace la lecture du code pour comprendre ce qui ne va pas.
