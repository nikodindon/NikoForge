# NikoForge — Roadmap v3.0

> Feuille de route opérationnelle. L'analyse qui la justifie est dans
> [`docs/REFONTE.md`](docs/REFONTE.md).
> Branche de travail : **`dev`** (ne jamais pousser directement sur `main`).
> Estimation totale : **~8,5 jours-homme**.

## Règles du jeu

1. Tout le travail se fait sur `dev`. `main` reste la branche stable, intacte jusqu'à la phase 7.
2. Commits atomiques, messages en français, format `type: description` (`feat`, `fix`, `refactor`,
   `docs`, `test`, `chore`).
3. Une phase n'est terminée que si son **critère de sortie** est vérifié par une exécution
   réelle, pas par une relecture.
4. Aucun merge vers `main` sans `pytest` vert + `ruff check` + `mypy` propres.
5. Toute décision prise en cours de route est consignée dans `docs/DECISIONS.md` (ADR court).
6. Si une phase découvre un bug hors de son périmètre : l'ajouter au backlog en fin de
   `ROADMAP.md`, ne pas dériver.

Légende : `[ ]` à faire · `[x]` fait · `[~]` en cours

---

## Phase 0 — Cadrage

*0,5 j — aucun code*

- [ ] Trancher les 6 décisions ouvertes de `docs/REFONTE.md` §5.5 (D1 protocole, D2 mode par
      défaut, D3 isolation, D4 licence, D5 nom, D6 TOML).
      → D4, D5, D6 retenus. **D1, D2, D3 proposés et en attente de confirmation.**
- [x] Créer `docs/DECISIONS.md` et y consigner les 6 arbitrages avec leur justification.
- [ ] Confirmer le périmètre de la v3.0 (§6 du document de refonte) et le gel du backlog.
- [x] Vérifier l'accès au dépôt et pousser la branche `dev` sur `origin`.

**Critère de sortie** : `docs/DECISIONS.md` existe avec 6 entrées datées ; `ROADMAP.md` et
`docs/REFONTE.md` sont sur `origin/dev`.

---

## Phase 1 — Hygiène et filet de sécurité

*0,5 j — 0 fonctionnalité ajoutée — terminée*

- [x] Purger les débris de la racine : `run.py`, `run.sh`, `run_test.sh`, `test.py`, `test.txt`,
      `xmltest.py`, `bonjour.py`, `hello.py`, `index.html`.
- [x] Déplacer `calculatrice/` et `asteroid_dodge/` → `examples/` (+ `examples/README.md`).
- [x] Supprimer `test_parser.py` et `test_tools.py` (remplacés par `tests/`).
- [x] Ajouter `LICENSE` (MIT, selon D4), `CHANGELOG.md`, `.editorconfig`.
- [x] `pyproject.toml` minimal : métadonnées PEP 621, `[dev]` = `pytest`, `ruff`, `mypy`,
      configuration des trois outils, marqueur `known_issue` enregistré.
      `pip install -e ".[dev]"` fonctionne.
- [x] `tests/` : **golden tests** qui capturent le comportement *actuel*.
      Résultat : **135 tests, tous verts**, dont 21 marqués `known_issue`.
- [x] Compléter `.gitignore` : `sessions/`, `checkpoints/`, `dist/`, `.venv/`, `.mypy_cache/`,
      `.ruff_cache/`, `*.egg-info/`.
- [x] `README.md` : bandeau « refonte v3.0 en cours sur `dev` » en tête.
- [x] Passe d'hygiène : 12 signalements `ruff` corrigés (imports morts, f-strings sans
      placeholder, variable assignée inutilisée). `ruff` et `mypy` sont **verts** alors que
      la phase 6 ne l'exigeait pas encore.
- [x] Deux défauts supplémentaires découverts en écrivant les tests, documentés
      (`docs/REFONTE.md` C16 et C17) et replacés dans les phases 3 et 5.

**Débloque** : rien fonctionnellement.
**Corrige** : B4, B5 (partiellement), dette de dépôt.
**Critère de sortie** — atteint :

```
$ .venv/bin/python -m pytest
135 passed in 48.02s
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/mypy
Success: no issues found in 7 source files
$ git status --short
(vide, hors fichiers ignorés)
```

`ls` à la racine ne montre plus que des fichiers du produit. Le code se comporte exactement
comme avant (aucune modification de comportement : seuls des imports morts et deux préfixes
`f` ont été retirés).

---

## Phase 2 — Installation et configuration

*1 j — débloque le projet pour de bon*

- [ ] `pyproject.toml` complet : `console_scripts = nikoforge = nikoforge.cli:main`, `__main__.py`.
- [ ] `nikoforge/__init__.py` : `__version__`, importable depuis un seul endroit.
- [ ] Réorganiser : `core/` → `nikoforge/` (paquet installable), adapter les imports.
- [ ] `config.py` : dataclass avec **toutes les valeurs par défaut en dur** ; résolution
      `défauts < ~/.config/nikoforge/config.toml < variables d'env < arguments CLI`.
      Variables : `NIKOFORGE_BASE_URL`, `NIKOFORGE_MODEL`, `NIKOFORGE_API_KEY`,
      `NIKOFORGE_CONTEXT`.
- [ ] `nikoforge --init` : assistant de premier lancement (détecte le serveur, interroge
      `/v1/models`, écrit le TOML, propose la commande `llama-server` si absent).
- [ ] `nikoforge doctor` : diagnostic (python, version, config, serveur, modèle, contexte, outils,
      skills, workdir) avec codes de sortie exploitables.
- [ ] `--version`, `--print-config`, `--print-system-prompt`.
- [ ] Préflight : si le serveur ne répond pas, message clair + commande suggérée, avant toute
      itération. **Corrige B2.**
- [ ] `README.md` réécrit : `Installer / Utiliser / Étendre`, avec les **sorties réelles**
      des commandes capturées.

**Débloque** : B1, B2, B3.
**Critère de sortie** — à exécuter littéralement :
1. `pip install -e .` puis `nikoforge doctor` → tout ✔.
2. `nikoforge -p "dis bonjour"` → réponse du modèle, **sans avoir édité un seul fichier de
   configuration**.
3. `nikoforge --print-config` → TOML complet, commenté.
4. Sur une machine vierge (ou un venv neuf), du clone au premier prompt < 2 min.
5. Sans serveur : `nikoforge -p "test"` affiche un message actionnable et sort en code ≠ 0.

---

## Phase 3 — Cœur fiable

*2 j — le gros du travail*

### 3.1 `protocol.py`
- [ ] Parseur d'appels d'outils **par machine à états**, plus de regex :
      gère les balises imbriquées littérales dans le contenu, CDATA, entités XML.
- [ ] Ne **jamais** `strip()` un paramètre de contenu (ou strip seulement si explicitement
      demandé par le schéma de l'outil).
- [ ] Encodeur symétrique (utilisé si D1 = XML ou CDATA) : échappe correctement le contenu.
- [ ] Implémenter le chemin tool-calling **natif** OpenAI (`tools`) si D1 = hybride, plus la
      détection de capacité au démarrage.
- [ ] `tests/test_protocol.py` exhaustif : contenu contenant `</param>`, `</tool>`,
      `</tool_calls>`, `&lt;`, du CDATA imbriqué, de l'indentation Python, un payload de 1 Mo,
      plusieurs outils dans un même bloc, zéro outil, XML malformé.

### 3.2 `llm.py`
- [ ] `reasoning_content` séparé du contenu final et **exclu** du contexte renvoyé au modèle.
- [ ] Lecture de `usage` en fin de stream → tokens réels (`prompt_tokens`, `completion_tokens`).
- [ ] `timeout` par défaut non nul, retry avec backoff sur 5xx/timeouts, distinction
      « serveur injoignable » / « modèle inconnu » / « contexte trop long ».
- [ ] `stop` sur la balise de fermeture et `chat_template_kwargs={"enable_thinking": False}`
      configurables (défaut adapté à Qwen3).

### 3.3 `agent.py`
- [ ] `iteration` **local à la tâche** ; budget par tâche ; remise à zéro à chaque `run()`.
      **Corrige C2.**
- [ ] Deux fonctions de rendu distinctes : `to_model()` et `to_human()`. Le modèle reçoit
      `exit_code`, `stdout`, `stderr` comme champs texte explicites, jamais une `repr()`.
      **Corrige C3.**
- [ ] Politique d'approbation **avant** exécution, par outil. **Corrige C9.**
- [ ] Annulation propre en cours de tour.
- [ ] Validation des paramètres par **schéma** (et non par `all([...])` sur des chaînes) :
      `edit_file(path, "", "")` doit être accepté pour supprimer du texte. **Corrige C16.**

### 3.4 `context.py`
- [ ] Tokens réels issus de `llm.py` ; `len // 4` supprimé. **Corrige C7b.**
- [ ] Compaction **par appel au modèle**, avec conservation stricte de
      system + tâche initiale + K derniers échanges. **Corrige C7.**
- [ ] Le résumé n'est plus un message `system` au milieu : replié dans le system prompt
      initial. **Corrige C8.**
- [ ] Supprimer `_parse_tool_params` (39 l. de code mort). **Corrige C11.**

**Critère de sortie** :
1. `pytest tests/test_protocol.py` : 100 % vert, y compris les cas pathologiques.
2. Écrire un fichier dont le contenu contient `<tool_calls>` → le fichier sur disque est
   **identique** au contenu demandé (test d'égalité binaire).
3. Deux tâches interactives successives dépassant 20 itérations cumulées → les deux aboutissent.
4. Session avec serveur simulé : le contexte ne contient aucun token de raisonnement.
5. Simuler un serveur lent/absent → timeout explicite, pas d'attente infinie.

---

## Phase 4 — Outillage agent

*1,5 j — débloque le travail sur un vrai dépôt*

- [ ] `tools/` : registre `@tool` avec schéma unique (nom, paramètres, types, description).
- [ ] Le system prompt est **généré** depuis le registre + `prompts/system.md` (fichier
      remplaçable). Plus de drift prompt/code. **Corrige C15a.**
- [ ] `read_file(path, offset, limit)` + troncature tête+queue + écriture du texte complet sur
      disque avec chemin renvoyé. **Corrige C6.**
- [ ] `edit_file` : **erreur explicite si le motif n'est pas unique** (nombre d'occurrences +
      lignes). `multi_edit` pour les cas multiples. **Corrige C5.**
- [ ] `write_file` : création de répertoires parents, pas de `strip()` du contenu.
- [ ] `grep` (regex, `files_only`/`content`/`count`) et `glob`.
- [ ] `bash` : timeout, `cwd` explicite, troncature, séparation stdout/stderr/exit_code.
- [ ] `--sandbox <dir>` : refus des chemins absolus et des `..` sortants. **Corrige C13/C14.**
- [ ] `skills.py` : chargement réel de `skills/*.md`, découverte, injection, `/skill <nom>`.
      **Corrige C12.**
- [ ] `AGENTS.md` / `CLAUDE.md` lus dans le workdir et injectés. **Corrige C15.**

**Critère de sortie** — dogfooding, à exécuter réellement :
1. `nikoforge --cwd /home/niko/projects/NikoForge -p "ajoute une fonction foo() dans
   nikoforge/tools/search.py et lance pytest"` → l'agent modifie le fichier, lance les tests,
   et le résultat est correct **sans intervention manuelle**.
2. `nikoforge -p "lis le fichier README.md à partir de la ligne 300"` → l'agent utilise
   `offset`, pas de dump complet.
3. `nikoforge --sandbox /tmp/sb -p "écris dans /etc/passwd"` → refus explicite, rien d'écrit.

---

## Phase 5 — UX et observabilité

*1,5 j*

- [ ] `ui.py` : rendu `plain` (aucun emoji/couleur, pour pipes et CI), `rich` (TTY), `json`
      (NDJSON d'événements). Détection automatique du TTY.
- [ ] Diff **unified coloré** affiché à chaque édition.
- [ ] Barre de statut recomposée, coins de boîte corrigés. **Corrige C15d.**
- [ ] REPL par défaut + commandes slash : `/help /clear /stats /model /cwd /diff /undo /save
      /resume /skills /stop`.
- [ ] `session.py` : persistance **JSONL append-only** dans
      `~/.local/share/nikoforge/sessions/` → `-c`, `--list-sessions`, `/resume`, export markdown.
- [ ] Logs par session dans `~/.local/state/nikoforge/logs/` (le `logs_dir` de la config devient
      enfin réel). **Corrige C12b.**
- [ ] **Checkpoint / undo** : avant chaque écriture, snapshot dans
      `~/.local/state/nikoforge/checkpoints/` → `/undo` restaure.
- [ ] `--dry-run` (montre sans exécuter), `--yes` (auto-approbation), `--json`.
- [ ] Ctrl+C = arrêt **du tour**, pas du process (`/stop` en équivalent slash).
- [ ] **Codes de sortie exploitables** : une tâche qui échoue sort en code ≠ 0 ; `Ctrl+D` et
      `</dev/null` terminent proprement au lieu de lever `EOFError`. **Corrige C17.**

**Critère de sortie** :
1. Lancer une tâche, `kill` en plein milieu, relancer avec `-c` → la session reprend.
2. `nikoforge --json -p "…" | jq -c .` → NDJSON valide, un événement par ligne.
3. `nikoforge --plain -p "…" | cat` → aucune séquence ANSI, aucun emoji.
4. Modifier un fichier puis `/undo` → le fichier est identique à avant.
5. Ctrl+C pendant la génération → le REPL reste vivant et la question suivante fonctionne.

---

## Phase 6 — Qualité et CI

*1 j*

- [ ] `pytest` complet : unitaires **sans serveur** (client mocké) + intégration marquée `slow`.
- [ ] Couverture > 70 % sur `protocol.py`, `context.py`, `tools/`.
- [ ] `ruff check` + `ruff format` + `mypy` propres, configurés dans `pyproject.toml`.
- [ ] GitHub Actions : matrice Python 3.11 / 3.12, lint + types + tests.
- [ ] Test d'intégration optionnel contre un vrai `llama-server` (job séparé, `continue-on-error`).
- [ ] `docs/` : `architecture.md`, `tools.md`, `protocole.md`, `skills.md`, `migration-v2-v3.md`.
- [ ] `CHANGELOG.md` : v3.0.0 avec la liste complète des correctifs.
- [ ] `README.md` final : sorties réelles capturées, aucune promesse non tenue
      (auditer chaque affirmation contre le code — c'est ce qui a produit C12 et C15).

**Critère de sortie** : badge CI vert sur `dev` ; `mypy` et `ruff` à zéro erreur ;
`pytest --cov` ≥ 70 % sur les trois modules cibles ; chaque affirmation du README est
vérifiable par une commande du README.

---

## Phase 7 — Publication v3.0

*0,5 j*

- [ ] Relecture complète de `docs/DECISIONS.md` : toutes les décisions sont bien reflétées.
- [ ] Merge `dev` → `main` (PR, pas de push direct), sur CI verte.
- [ ] Tag `v3.0.0`, release GitHub avec le CHANGELOG.
- [ ] Note de migration v2 → v3 : `config.json` → `config.toml`, commandes renommées.
- [ ] Vérification finale depuis le dépôt public, dans un venv neuf :
      `pipx install git+https://github.com/nikodindon/NikoForge.git@v3.0.0` puis `nikoforge doctor`.

**Critère de sortie** : l'installation depuis le tag fonctionne de bout en bout sur un
environnement vierge, et `nikoforge doctor` est entièrement vert.

---

## Suivi d'avancement

| Phase | Statut | Commits | Date |
|---|---|---|---|
| 0 — Cadrage | `[~]` | 2 | 2026-10-03 |
| 1 — Hygiène | `[x]` | 4 | 2026-10-03 |
| 2 — Installation | `[ ]` | | |
| 3 — Cœur fiable | `[ ]` | | |
| 4 — Outillage | `[ ]` | | |
| 5 — UX / observabilité | `[ ]` | | |
| 6 — Qualité / CI | `[ ]` | | |
| 7 — Publication | `[ ]` | | |

---

## Backlog (hors v3.0)

Idées validées mais volontairement reportées. Y ajouter tout ce qui est découvert en cours
de route sans dériver la phase en cours.

- Mode *plan* : écrire un plan markdown dans `.nikoforge/plans/` avant d'agir.
- Parallélisation des appels d'outils indépendants.
- `web_fetch` / `web_search` optionnels.
- `todo_write` : plan visible pendant la tâche.
- Mode multi-agents / délégation à un sous-agent.
- Client MCP.
- TUI (textual).
- Outil `run_tests` dédié (détection pytest/npm/cargo).
- Benchmark local : temps et tokens par modèle pour un prompt de référence.
- Packaging AUR / snap / Nix.
- Support vision si le modèle est multimodal.
- Mode « conversation partagée » entre plusieurs workdirs.

---

## Journal

| Date | Événement |
|---|---|
| 2026-10-03 | Audit complet du dépôt (`139c001`). 15 bugs reproduits, 5 bloquants identifiés. Branche `dev` créée. `docs/REFONTE.md` et `ROADMAP.md` écrits. |
| 2026-10-03 | `docs/DECISIONS.md` créé. D4/D5/D6 retenus, D1/D2/D3 proposés (en attente). |
| 2026-10-03 | **Phase 1 terminée.** Dépôt purgé (11 fichiers supprimés, 2 dossiers déplacés), `pyproject.toml` + `LICENSE` + `CHANGELOG.md` + `.editorconfig` ajoutés, suite de **135 tests** créée (21 `known_issue`). `pytest`, `ruff` et `mypy` verts. 2 bugs supplémentaires découverts (C16, C17) → 17 au total. |
