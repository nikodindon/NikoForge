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

- [x] Trancher les décisions ouvertes de `docs/REFONTE.md` §5.5.
      **D1** tranché **par la mesure** (sonde du serveur réel : `GET /v1/models` annonce
      `capabilities: ["completion"]` — faux ; `GET /props` → `chat_template_caps.supports_tools:
      true` ; un appel avec `tools` renvoie de vrais `tool_calls`). → hybride, détection sur
      `/props`. Détail dans `docs/DECISIONS.md`.
      **D2** implémenté en phase 2 (REPL par défaut). **D4** (MIT), **D5** (`nikoforge`),
      **D6** (TOML) retenus.
      **D3 (isolation) reste ouvert** — à trancher avant la phase 4, qui touche au bac à sable
      des écritures.
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

*1 j — débloque le projet pour de bon — terminée*

- [x] `pyproject.toml` complet : `console_scripts = nikoforge = nikoforge.cli:main`,
      ``__main__.py`` pour `python -m nikoforge`. Version **dynamique** lue dans
      `nikoforge/__init__.py` (source unique de vérité).
- [x] `nikoforge/__init__.py` : `__version__ = "3.0.0.dev0"`, import différé (``import
      nikoforge`` ne charge pas `openai`, pour que `doctor` et `--version` fonctionnent même
      si la dépendance est cassée).
- [x] Réorganisé : `core/` → `nikoforge/` (paquet installable). `nikoforge.py` supprimé.
- [x] `config.py` : dataclasses gelées, **toutes les valeurs par défaut en dur**, précédence
      complet `défauts < TOML < environnement < CLI`. 10 variables `NIKOFORGE_*`. Clé ou
      section inconnue → erreur explicite. `render_toml` / `write_config` (écriture atomique)
      avec aller-retour TOML fidèle.
- [x] `nikoforge init` (et l'alias `--init`) : sonde le serveur, lit `/v1/models`, choisit le
      modèle, écrit un TOML complet et commenté ; si le serveur est absent, affiche la commande
      `llama-server` avec un GGUF local trouvé automatiquement.
- [x] `nikoforge doctor` : 10 contrôles, un remède par échec, code de sortie exploitable.
- [x] `requirements.txt` et `config.example.json` supprimés (redondants avec `pyproject.toml`
      et les défauts en dur).
- [x] `--version`, `--print-config`, `--print-system-prompt`.
- [x] Pré-vol : `GET /v1/models` testé **avant** la première itération, avec la commande à
      copier et sortie en code 3. **Corrige B2.**
- [x] `README.md` réécrit en `Installer / Utiliser / Étendre`, sorties réelles recopiées.
      Ajout de `docs/migration-v2-v3.md` et `docs/prompts.md`.
- [x] Correctifs attrapés en cours de route :
      - `probe()` levait une exception sur une URL sans schéma alors que son contrat est de ne
        jamais lever (attrapé par `test_probe_never_raises_whatever_the_url`) ;
      - `edit_file` impossible à utiliser pour **supprimer** du texte (bug C16, confirmé par
        un test) ;
      - **C17 largement corrigé** : code de sortie 3 sans serveur, 1 quand la tâche ne produit
        rien, `Ctrl+D` traité proprement. Le reste (échec en cours de tour, `--json`) est en
        phase 5.

**Débloque** : B1, B2, B3 — le projet démarre désormais sans aucun fichier de configuration.
**Critère de sortie** — les cinq vérifiés par exécution réelle :

1. `doctor` → `Tout est opérationnel`, code 0 ✔
2. `nikoforge -p "dis bonjour"` → réponse du modèle, **aucun fichier de configuration créé
   ni lu** (vérifié : `~/.config` n'existe pas après l'exécution) ✔
3. `--print-config` → TOML complet et commenté, ré-analysable ✔
4. venv neuf, du clone au premier prompt < 2 min ✔ (voir le journal)
5. sans serveur → message actionnable + `llama-server -m …` à copier, code de sortie 3 ✔

Résultat de la suite : **246 tests**, `ruff` et `mypy` propres.

---

## Phase 3 — Cœur fiable

*2 j — terminée*

### 3.1 `protocol.py`
- [x] Parseur d'appels d'outils **par machine à états**, plus de regex : chaque paramètre est
      consommé en entier, CDATA compris, donc un `</tool>` **dans** le contenu ne peut plus
      terminer le corps de la balise.
- [x] Aucun `strip()` : seul **un** saut de ligne de tête et de queue est retiré, et jamais
      dans un CDATA. L'indentation et le saut de ligne final survivent.
- [x] Encodeur symétrique : CDATA dès qu'un caractère est ambigu, repli sur les entités
      seulement quand le contenu contient `]]>` (impossible en CDATA).
- [x] Chemin natif OpenAI (`tools`) **et** détection de capacité réelle sur `/props`.
      Les deux formes sont acceptées en lecture, même mélangées.
- [x] `tests/test_protocol.py` : **103 tests**, dont un aller-retour encodeur/décodeur sur
      17 contenus piégés (`</param>`, `</tool>`, `</tool_calls>`, CDATA imbriqué, indentation,
      CRLF, 100 000 caractères, vide).

### 3.2 `llm.py`
- [x] `reasoning_content` conservé à part, jamais renvoyé au modèle. **Corrige C4.**
- [x] `usage` lu en fin de flux → tokens réels. **Corrige C7b.**
- [x] `timeout` à 300 s par défaut, reprise avec attente doublée sur 5xx/timeouts, erreurs
      nommées (`ServerUnreachable`, `ModelNotFound`, `ContextTooLong`, `ToolsUnsupported`…).
      **Corrige C10.** Les reprises du SDK `openai` sont désactivées pour n'avoir **qu'une**
      politique, visible et testée.
- [x] `stop` et `enable_thinking` configurables ; repli automatique du protocole natif vers le
      textuel quand le serveur refuse `tools` (sauf si le protocole est forcé).
- [x] Réassemblage des `tool_calls` **fragmentés** : llama.cpp les envoie morceau par morceau,
      un client naïf lit du JSON tronqué.

### 3.3 `agent.py`
- [x] `iteration` **local à la tâche**. **Corrige C2.**
- [x] `render_result_for_model` (champs explicites) distinct de `format_tool_result`
      (affichage humain). **Corrige C3.**
- [x] Approbation **avant** exécution, par outil, avec `auto_approve`, `allow_always` et un
      refus expliqué au modèle. **Corrige C9.**
- [x] Annulation (`should_stop`) vérifiée à chaque tour.
- [x] Validation par **schéma** de `protocol` : `new_content=""` accepté. **Corrige C16.**
- [x] Sorties bornées, tête **et** queue. **Corrige C6** (volet affichage).
- [x] **C18, découvert en usage réel** : l'historique suit le protocole OpenAI — message
      assistant porteur des `tool_calls`, résultats en `role: "tool"` avec `tool_call_id`.
      Sans cela le modèle rappelait l'outil indéfiniment (6 itérations au lieu de 3).

### 3.4 `context.py`
- [x] Tokens réels issus de `usage`, complétés par une estimation de ce qui suit la mesure.
      **Corrige C7b.**
- [x] Compaction **par appel au modèle**, tête épinglée + K derniers messages. **Corrige C7.**
- [x] Résumé replié dans le message `system` initial. **Corrige C8.**
- [x] `_parse_tool_params` supprimé avec le reste du code mort. **Corrige C11.**
- [x] La compaction ne coupe jamais entre un message assistant porteur d'appels et ses
      résultats (`tool` orphelin = gabarit de chat en échec).

**Critère de sortie** — les cinq vérifiés, plus un bout en bout réel :

1. `pytest tests/test_protocol.py` → **103 tests, 100 % verts**, cas pathologiques inclus ✔
2. Écrire un fichier dont le contenu contient `<tool_calls>` → contenu identique ✔ (test
   d'aller-retour sur 17 contenus piégés)
3. Deux tâches interactives successives avec un budget d'itérations consommé → les deux
   aboutissent ✔ (`test_the_iteration_budget_is_per_task`)
4. Serveur simulé : aucun token de raisonnement dans le contexte ✔
5. Serveur absent ou lent → erreur nommée, reprise bornée, jamais d'attente infinie ✔

**Et surtout, la vérification qui a trouvé un vrai bug** : deux tâches réelles contre le
`llama-server` de l'auteur (modèle `Ornith-1.5-35B-IQ2_M`, protocole **natif** détecté sur
`/props`) :

```
$ nikoforge --base-url http://100.91.114.49:8080/v1 --cwd /tmp/nf_e2e --max-iterations 6 \
    -p "Cree un fichier hello.py qui affiche Bonjour NikoForge, puis execute-le pour verifier."
 ⚕ Ornith-1.5-35B-IQ2_M │ ctx 1245/32768 │ 3 itérations │ ⏲ 16.7s
C'est fait ! ✅
- ✅ `hello.py` créé avec `print("Bonjour NikoForge")`
- ✅ Exécuté avec succès
- Sortie : `Bonjour NikoForge`
✓ Terminé !
$ echo $?
0
```

Puis, sur le même dossier, une tâche d'édition (5 itérations, code 0) : `Bonjour` → `Bonsoir`
appliqué, script relancé, sortie réelle rapportée par le modèle.

Résultat de la suite : **416 tests**, `ruff` et `mypy` propres.

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
- [ ] **Réécrire `AGENTS.md`** : il décrit aujourd'hui un format `[outil: nom_outil]` que le
      code n'a jamais implémenté (le format réel est XML, et il change en phase 3). C'est le
      premier fichier lu par tout agent travaillant sur ce dépôt — il doit dire la vérité.

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
- [ ] **Codes de sortie exploitables** : compléter C17 (largement corrigé en phase 2 : sortie
      3 sans serveur, 1 si la tâche ne produit rien, `Ctrl+D` propre) — reste l'échec en cours
      de tour et le mode `--json`.

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
| 2 — Installation | `[x]` | 6 | 2026-10-03 |
| 3 — Cœur fiable | `[x]` | 4 | 2026-10-03 |
| 4 — Outillage | `[ ]` | | |
|| 5 — UX et observabilité | `[~]` | 1 | 2026-10-03 |
|| 6 — Qualité et CI | `[~]` | 0 | 2026-10-03 |
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
| 2026-10-03 | **Phase 2 terminée.** `core/` → paquet `nikoforge/` installable, `config.py` (défauts complets + TOML + 10 variables d'env), `server.py`, `doctor.py`, `wizard.py`, `cli.py` réécrit (sous-commandes, 4 codes de sortie). `requirements.txt` et `config.example.json` supprimés. README réécrit, `docs/migration-v2-v3.md` et `docs/prompts.md` ajoutés. **246 tests**, verts. B1, B2, B3 corrigés ; C17 largement corrigé. Les 5 critères de sortie vérifiés par exécution réelle. |
| 2026-10-03 | Critère 4 mesuré sur un clone **neuf** de `origin/dev` : `git clone` + `python -m venv` + `pip install -e .` = **11 s**, premier prompt à **12 s** (budget : 2 min). `doctor` entièrement vert sur cette installation neuve, puis **246 tests** verts, `ruff` et `mypy` propres — le tout sur le clone, pas sur le dépôt de travail. |
| 2026-10-03 | **Phase 3 terminée.** Quatre modules : `protocol.py` (machine à états + CDATA + natif, 103 tests), `llm.py` (streaming, outils fragmentés, raisonnement à part, reprises, erreurs nommées), `agent.py` (itération par tâche, rendu modèle/humain, approbation), `context.py` (tokens réels, compaction par le modèle, tête épinglée). **416 tests**, verts. C1, C2, C3, C4, C6 (affichage), C7, C7b, C8, C9, C10, C11, C16 corrigés. D1 tranché par la mesure sur un serveur réel. |
| 2026-10-03 | **Bug C18 trouvé par les tests réels** : les appels d'outils natifs n'étaient pas structurés pour le gabarit de chat (message assistant vide, résultats en `user`) — le modèle rappelait l'outil indéfiniment. Corrigé : `tool_calls` dans le message assistant, résultats en `role: "tool"`. Même tâche réelle : 6 itérations/code 1 → **3 itérations/code 0**. Invisible en test simulé ; argument pour un test d'intégration `llama-server` en phase 6. |
