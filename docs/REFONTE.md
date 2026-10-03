# NikoForge — Audit et refonte (v3.0)

> Document de cadrage. Décrit l'état réel du projet au commit `139c001` (branche `main`,
> 2026-05-26), les défauts **reproduits**, puis la refonte proposée.
> La feuille de route opérationnelle est dans [`ROADMAP.md`](../ROADMAP.md).

---

## 0. Méthode

Tout ce qui suit a été vérifié en lisant les 32 fichiers du dépôt **et** en exécutant du code.
Les sorties citées sont des sorties réelles, non retouchées (parasites et codes de retour inclus).
Script de reproduction : `/tmp/nf_repro.py` (à déplacer dans `tests/manual/` si on veut le garder).

Environnement de vérification :

```
Python 3.12.3
openai 2.41.1
/usr/local/bin/llama-server   (présent, non lancé)
curl http://localhost:8080/v1/models   -> vide (serveur arrêté)
```

---

## 1. État des lieux

| | |
|---|---|
| Dernier commit | `139c001` — 2026-05-26 (~4 mois) |
| Commits | 11 |
| Code Python réel | 957 lignes (dont 39 mortes : `_parse_tool_params`) |
| Dépendance | `openai>=1.0.0` (unique) |
| Fichiers suivis | 32, dont **18 qui ne sont pas du code produit** (9 débris, 2 pseudo-tests, 7 fichiers de démo) |
| Tests | 3 scripts d'affichage, 0 test exécutable sans serveur |

Modules du cœur :

```
nikoforge.py      172 l.   point d'entrée CLI
core/agent.py     291 l.   boucle ReAct, parsing XML, routage outils
core/tools.py     146 l.   read/write/edit/bash/list_files
core/context.py   129 l.   historique + compaction
core/ui.py        166 l.   affichage (emoji, boîtes ASCII)
core/prompt.py     37 l.   system prompt (f-string jamais formaté)
```

Structure actuelle du dépôt :

```
AGENTS.md              <- documente un format d'outil que le code n'utilise PAS
README.md  432 l.      <- docs longues, partiellement fausses
config.example.json
requirements.txt       <- "openai>=1.0.0"
run.py                 <- DÉBRIS (sortie de modèle : "```" + "No, that's overkill.")
run.sh run_test.sh     <- DÉBRIS (lignes "```" casse-shell)
test.py test.txt       <- DÉBRIS
xmltest.py             <- DÉBRIS (print('XML rocks!'))
bonjour.py hello.py    <- DÉBRIS (hello.py est vide, 0 octet)
index.html             <- DÉBRIS (page générée)
test_parser.py test_tools.py  <- scripts d'affichage, pas des tests
skills/                <- 2 .md jamais lus par le code
calculatrice/ asteroid_dodge/ <- projets de DÉMO générés par l'agent, committés à la racine
```

**18 des 32 fichiers suivis ne sont pas du code produit** : 9 résidus d'exécutions de l'agent
(`run.py`, `run.sh`, `run_test.sh`, `test.py`, `test.txt`, `xmltest.py`, `bonjour.py`,
`hello.py` vide, `index.html`), 2 pseudo-tests sans assertions (`test_parser.py`,
`test_tools.py`) et les 7 fichiers de deux projets de démo (`calculatrice/`, `asteroid_dodge/`).
L'agent écrit dans `.` — c'est `base_dir` par défaut, `core/agent.py:26`. Les deux démos sont
la preuve que l'agent fonctionnait — mais elles n'ont rien à faire dans le dépôt du produit.

---

## 2. Bloquants (le projet ne démarre pas tel quel)

### B1 — `config.json` obligatoire, absent et gitignoré

`Agent._load_config()` lève `FileNotFoundError` (`core/agent.py:38-39`) et `nikoforge.py:72-74`
fait `sys.exit(1)`. Réel, exécuté sur le dépôt lui-même :

```
$ python3 nikoforge.py "dis bonjour"
    ╚══════════════════════════════════════════════════════════════╝


❌ Erreur: Erreur d'initialisation: Configuration non trouvée: config.json
$ echo $?
1
```

L'installation README demande de copier `config.example.json` à la main, puis d'éditer du JSON.
C'est le premier obstacle à la simplicité — et il est inutile.

### B2 — aucun diagnostic si `llama-server` est absent

`OpenAI(...)` ne se connecte pas à l'initialisation. Le serveur arrêté ne se voit qu'à la
**première** itération, où l'exception est avalée (`core/agent.py:152-154`) :

```
✗ Erreur modèle: Connection error.
✗ Pas de réponse du modèle
```

Aucun message actionnable (« lancez `llama-server -m ... --port 8080` »), aucune distinction
entre « serveur éteint », « mauvais port » et « modèle inconnu ».

### B3 — aucune installation packagée

Pas de `pyproject.toml`, pas d'`entry point`, pas de `__main__.py`. Impossible de faire
`pipx install nikoforge`, `uv tool install`, ni `python -m nikoforge`. Il faut un venv manuel,
un `cd` dans le dépôt, et `python nikoforge.py`.

### B4 — les scripts fournis sont inutilisables

```
$ bash run.sh
run.sh: ligne 2: ./venv/bin/python: Aucun fichier ou dossier de ce nom
$ bash run_test.sh
  File "/home/niko/projects/NikoForge/test.py", line 2
    ```
    ^
SyntaxError: invalid syntax
$ python3 test_parser.py
FileNotFoundError: Configuration non trouvée: config.json
```

`run.sh` pointe un venv inexistant ; `run_test.sh` lance `test.py`, qui est un débris de sortie
de modèle contenant des backticks Markdown.

### B5 — les « tests » ne testent rien

`test_tools.py` et `test_parser.py` sont des scripts qui **affichent** des résultats à l'écran,
sans aucune assertion, et sortent en code 0 quoi qu'il arrive. Aucun ne tourne sans
`config.json`, aucun n'est branchable sur la CI.

---

## 3. Bugs de la boucle (tous reproduits)

Les sorties ci-dessous viennent de `/tmp/nf_repro.py`, exécuté sans serveur LLM.

### C1 — le parser XML casse sur le contenu généré (critique)

`_extract_tool_calls` (`core/agent.py:156-186`) est du regex : `(.*?)</tool>`, `(.*?)</param>`.
Dès que le **fichier écrit** contient `</tool>`, `</param>` ou `</tool_calls>` — c'est-à-dire
dès qu'on écrit du HTML, du SVG, du Markdown documentant le format… ou le README de ce projet —
le parsing tronque silencieusement le contenu.

```
BUG C1a - le contenu genere contenant </tool> casse le parser XML
nb d'appels detectes : 1
  nom   : write_file
  params: ['path', 'content']
  [content] len=82 derniers 30 car. = 'ash">\n<param name="command">ls'
>>> Le fichier ecrit perd tout apres le premier '</tool>' imbrique : 82 caracteres sur 180 attendus
```

Trois sous-défauts du même point :

```
BUG C1b - .strip() detruit le whitespace de tete/queue du contenu ecrit
contenu extrait : 'indentation_attendue = True\n    return indentation_attendue'
>>> l'indentation de la 1re ligne et le \n final sont perdus (Python: IndentationError)

BUG C1c - les entites XML ne sont pas decodees
contenu extrait : '&lt;div&gt;&amp;nbsp;&lt;/div&gt;'
>>> le modele qui echappe correctement produit du &lt; litteral dans le fichier
```

`.strip()` est appliqué à **tout** paramètre (`core/agent.py:179`), y compris `content`.
Un modèle qui indente correctement son code en début de valeur produit un fichier qui ne
compile pas. Un modèle qui échappe correctement produit des fichiers pleins d'entités.
Les deux échecs sont muets : `write_file` renvoie « ✓ Fichier écrit ».

### C2 — `iteration` n'est jamais remis à zéro : budget de session, pas de tâche

`self.iteration` est initialisé au constructeur (`core/agent.py:32`) et seulement incrémenté.
`max_iterations` (défaut 20) est donc un **budget global de session**. Passé 20 itérations
cumulées, la boucle `while` ne rentre plus :

```
BUG C2 - iteration jamais remise a zero : budget de SESSION, pas de tache
retour de run() : ''
messages ajoutes au contexte : ['user']
>>> aucune erreur, aucun message : l'agent ne fait plus RIEN apres 20 iterations cumulees
```

En mode interactif, la 3ᵉ ou 4ᵉ tâche de la session devient donc un no-op silencieux.
C'est le bug le plus vicieux du lot : aucune trace, aucun code de retour.

### C3 — le modèle reçoit une `repr()` Python au lieu de la sortie brute

`core/agent.py:100` construit le message destiné au **modèle** avec `format_tool_result()`,
une fonction écrite pour l'humain :

```
BUG C3 - le modele recoit une repr Python, pas la sortie brute
message envoye au MODELE :
"[outil: bash]\n✓ Succès\nDonnées: {'stdout': 'total 8\\n-rw-r--r-- 1 niko niko 12 file.txt\\n', 'stderr': '', 'exit_code': 0}\n"
```

Le modèle doit déchiffrer un littéral Python avec ses `\\n` échappés, un `✓` et un préfixe
français. `stdout`, `stderr` et `exit_code` ne lui sont pas présentés comme des champs distincts.
C'est une perte directe de qualité de raisonnement, pour zéro bénéfice.

### C4 — `reasoning_content` est fusionné dans le contenu final

`core/agent.py:146-148` : si `content` est absent, on prend `reasoning_content` et on
l'accumule dans `full_content`, qui devient le message assistant stocké au contexte.
Sur un modèle cible **Qwen3**, tout le bloc de réflexion entre dans l'historique et est
renvoyé à chaque tour. Aucun `chat_template_kwargs={"enable_thinking": False}`, aucun `stop`
sur `</tool_calls>` : on paie les tokens de raisonnement deux fois (génération + relecture
à chaque itération) alors que le README revendique la sobriété.

### C5 — `edit_file` remplace **toutes** les occurrences sans le dire

`core/tools.py:73` utilise `str.replace(old, new)`, qui remplace *toutes* les occurrences.
Aucune vérification d'unicité :

```
BUG C5 - edit_file remplace TOUTES les occurrences sans le dire
resultat : {'success': True, 'data': 'Fichier modifié: multi.py', 'error': None}
contenu final :
x = 999
y = 2
x = 999
>>> les 2 occurrences ont ete modifiees silencieusement
```

Pour un agent, c'est une corruption de fichier déguisée en succès. Le comportement correct
(et standard) est : erreur explicite si le motif n'est pas unique, avec le nombre d'occurrences
et leurs lignes.

### C6 — aucune borne sur les entrées/sorties

`read_file` lit le fichier entier et n'a pas de `offset`/`limit` :

```
BUG C6 - read_file/bach sans borne
read_file d'un fichier de 5000 car. -> renvoie 5000 caracteres, sans offset/limit
read_file a-t-il un parametre offset ? False
```

`bash` (`core/tools.py:82-107`) renvoie `stdout` + `stderr` complets. Un `cat` sur un gros
fichier ou une commande verbeuse explose le contexte en une itération. Il n'existe **aucun
moyen** pour le modèle de lire la fin d'un fichier de 3000 lignes.

### C7 — compaction destructrice et non-LLM

Le README annonce « génère un résumé des messages anciens ». En réalité `_generate_summary`
(`core/context.py:73-93`) **concatène les messages bruts** et tronque par `summary[:len-100]`,
c'est-à-dire coupe au milieu d'un mot :

```
BUG C7 - compaction : la tache initiale disparait du contexte actif
avant compaction : 13 messages
apres compaction : ['assistant', 'user']
resume brut => coupe au milieu d'un mot : 'r]: resultat outil 3 sortie sortie sortie sortie sortie s...'
>>> la 1re question utilisateur (l'objectif) n'est plus dans le contexte actif
```

`compact()` (`core/context.py:59-71`) ne garde que les **2 derniers messages** : la tâche
initiale n'est plus dans le contexte actif, et le « résumé » n'est qu'un tas de bruit tronqué.
Sur 32 k de contexte c'est un générateur d'hallucinations.

Corollaire : `estimate_tokens = len(text) // 4` (`core/context.py:42`) est faux pour du code
(~3 car./token) et catastrophique hors ASCII. Le serveur renvoie pourtant un `usage` exact
en fin de stream, qui n'est jamais lu.

### C8 — le résumé est injecté comme message `system` au milieu de la conversation

`core/context.py:32-35` insère `{"role": "system", "content": "Résumé…"}` en tête de
`get_messages()`, lui-même précédé du vrai system prompt (`core/agent.py:118-121`).
On envoie donc **deux messages system** consécutifs. Les templates Jinja de llama.cpp
(`--jinja`, obligatoire pour Qwen3) ne le garantissent pas. Le résumé doit être replié dans
le system prompt initial ou passé en message `user` balisé.

### C9 — la confirmation interactive arrive **après** l'exécution

`core/agent.py:104-111` demande « Continuer? (o/n/q) » après la boucle `for tool_call in
tool_calls` — donc après que `bash`, `write_file` et consorts ont déjà été exécutés.
La confirmation ne protège rien. Elle doit porter sur l'exécution, outil par outil,
avec une politique (`read` = autorisé, `bash`/`write` = demandé).

### C10 — aucun timeout de connexion, aucun retry

`config.example.json` met `"timeout": null` et le client est construit sans timeout
(`core/agent.py:49-52`). Si `llama-server` se bloque, la boucle attend indéfiniment.
Aucune gestion des 500/503, aucun backoff, aucune reprise de stream.

### C11 — 39 lignes de code mort

`_parse_tool_params` (`core/agent.py:188-226`) date du format `clé: valeur` de la v1, remplacé
par le XML en v2. Il n'est plus appelé que par `test_parser.py` :

```
grep -rn "_parse_tool_params" --include=*.py
test_parser.py:17,32,43
core/agent.py:188
```

### C12 — trois fonctionnalités fantômes déclarées mais inexistantes

```
config declare : ['projects_dir', 'logs_dir', 'skills_dir']
  paths.projects_dir = 'projects' -> 0 occurrence(s) dans le code Python
  paths.logs_dir     = 'logs'      -> 2 occurrence(s) dans le code Python
  paths.skills_dir   = 'skills'    -> 0 occurrence(s) dans le code Python
skills/ lu par le code ? False
```

Le dossier `skills/` — documenté, avec son `README.md` qui explique « comment créer un skill »
et promet un chargement automatique — **n'est lu par aucune ligne de code**. Idem pour
`logs/` (rien n'écrit de log) et `projects/`. Les 2 occurrences de `logs` sont le `.gitignore`
et le README. Trois promesses non tenues dans la doc.

### C13 — aucune isolation (sandbox)

`Tools(base_dir=".")` — l'agent travaille dans le dépôt, d'où les 9 débris à la racine.
`_resolve_path` (`core/tools.py:131-136`) accepte les chemins absolus et `../` sans contrôle :

```
BUG C14 - aucune sandbox : ecriture hors du base_dir acceptee
write_file('../../tmp/...') -> {'success': True, 'data': 'Fichier écrit: /tmp/nf_repro_work/../../tmp/nf_hors_sandbox.txt', ...}
fichier cree hors base_dir ? True
base_dir = /tmp/nf_repro_work
```

Ce n'est pas forcément un défaut pour un agent local mono-utilisateur (« tout est auditable »),
mais alors il faut l'assumer : ni `base_dir`, ni `projects_dir` n'ont de sens aujourd'hui,
et le README laisse croire à un confinement.

### C15 — dérive documentaire

- `AGENTS.md` (le fichier que TOUT agent lisant ce dépôt lit en premier) documente un format
  `[outil: nom_outil]`… que le code n'implémente pas : il fait du XML depuis la v2.
- README ligne 333 : `"max_tokens": 2048` alors que `config.example.json` dit `8192`.
- README : compaction « à 25600 tokens (80 % de 32000) » vs la config `max_tokens: 32000`
  et l'exemple llama-server `--context 65536`.
- La version `v2.0` est une chaîne en dur dans `core/ui.py:24` et `:43`, pas une constante.
- `print_header` ouvre avec `╭…╮` et ferme avec `╰…╮` (`core/ui.py:51`) — coin incohérent.

---

## 4. Ce qui est bon et qu'on garde

1. **La philosophie** : harness minimal, le modèle fait le travail. C'est le bon choix pour
   un modèle local de 35 B. Rien à jeter.
2. **La boucle ReAct** est lisible et tient en une méthode. Le format « réponse libre +
   appel d'outil balisé + résultat renvoyé » est le bon patron pour un modèle non
   tool-native.
3. **L'idée d'un format texte balisé** pour les modèles qui n'ont pas de tool-calling natif
   reste pertinente (voir D1) — c'est l'implémentation regex qui est fautive, pas le principe.
4. **Le découpage tools / context / prompt / ui** existe déjà. La refonte le pousse, elle
   ne le remplace pas.
5. **Le README est riche** en exemples de prompts : c'est du bon matériau, à déplacer dans
   `docs/` après vérification.
6. La preuve de fonctionnement est là : `calculatrice/` et `asteroid_dodge/` ont été produits
   par l'agent et sont corrects.

---

## 5. Refonte proposée

### 5.1 Les six axes

| Axe | Objectif mesurable |
|---|---|
| **A. Installation** | du `git clone` au premier prompt en < 2 min, **zéro édition de fichier** |
| **B. Fiabilité de la boucle** | parser qui ne casse jamais sur le contenu généré ; itération par tâche ; erreurs explicites |
| **C. Outillage agent** | grep/glob, lecture par morceaux, édition sûre, sorties bornées → l'agent peut travailler sur un vrai dépôt |
| **D. Observabilité** | sessions persistantes et reprenables, logs, `--dry-run`, `--json`, `doctor` |
| **E. Extensibilité** | skills réellement chargés, `AGENTS.md` honoré, outils pluggables, prompt généré depuis le registre d'outils |
| **F. Qualité** | `pyproject.toml`, pytest, ruff, mypy, CI 3.11/3.12, dépôt sans débris |

### 5.2 Installation : avant / après

**Avant** (README actuel) — 6 étapes, dont 2 manuelles et fragiles :

```bash
git clone https://github.com/nikodindon/NikoForge.git && cd NikoForge
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./llama-server -m /home/niko/models/Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf \
  -c 65536 --jinja --flash-attn on -ngl 999 --cache-type-k q8_0 --cache-type-v q8_0 \
  -b 512 -ub 512 --threads 8 --threads-batch 6 --kv-offload --mlock --port 8080 --host 0.0.0.0
cp config.example.json config.json    # puis éditer le JSON à la main
python nikoforge.py                    # échoue si on a oublié une étape
```

**Après** — 2 commandes, dont une seule obligatoire :

```bash
uv tool install nikoforge        # ou pipx install nikoforge
nikoforge                        # 1er lancement = assistant de configuration
```

Le premier lancement :

1. cherche un serveur OpenAI-compatible sur `localhost:8080` ;
2. si trouvé, interroge `/v1/models` et **choisit le modèle** ;
3. sinon, affiche la commande `llama-server` à copier (détecte le binaire, propose les GGUF de `~/models`) ;
4. écrit `~/.config/nikoforge/config.toml` — complet, avec toutes les valeurs par défaut ;
5. lance le REPL.

Zéro édition manuelle. Un `nikoforge doctor` rejoue le diagnostic à tout moment :

```
$ nikoforge doctor
✔ Python 3.12.3
✔ paquet nikoforge 3.0.0
✔ config       ~/.config/nikoforge/config.toml
✔ serveur      http://127.0.0.1:8080  (llama-server, 1.2 s)
✔ modèle       Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf
✔ contexte     65536 tokens annoncés
✔ outils       read_file write_file edit_file bash grep glob multi_edit
✔ skills       1 chargeable (python-development)
⚠ workdir      /home/niko/projects/NikoForge — 13 fichiers non suivis (suggestions : .gitignore)
```

### 5.3 Utilisation cible

```bash
nikoforge                            # REPL interactif (défaut)
nikoforge -p "crée un script qui analyse des logs"     # one-shot
nikoforge -c                         # reprend la dernière session
nikoforge --list-sessions
nikoforge --model qwen3.6-35b --cwd ~/projets/truc
nikoforge --dry-run "ajoute une docstring à utils.py"  # montre sans exécuter
nikoforge --yes  /  --json  /  --plain
nikoforge doctor
nikoforge --print-system-prompt      # debug
```

Dans le REPL, des commandes slash :

```
/help  /clear  /stats  /model  /cwd  /diff  /undo  /save  /resume  /skills  /skill <nom>  /stop
```

### 5.4 Architecture cible

```
nikoforge/
  __init__.py        __version__ (source unique de vérité)
  __main__.py        -> python -m nikoforge
  cli.py             argparse/typer : sous-commandes, REPL, options
  config.py          dataclass/pydantic : defaults en dur + TOML + variables d'env
  llm.py             client OpenAI-compatible : streaming, retry, timeout, reasoning séparé, usage réel
  protocol.py        (dé)codage des appels d'outils — PUR, sans I/O, testable à 100 %
  agent.py           boucle : budget PAR TÂCHE, annulation, hooks, politiques d'approbation
  context.py         tokens réels (usage), compaction LLM, conservation system+tâche+K tours
  session.py         persistance JSONL append-only, reprise, export markdown
  skills.py          chargement skills/ + AGENTS.md, injection, découverte
  prompts/
    system.md        prompt système en FICHIER (remplaçable par l'utilisateur)
  tools/
    __init__.py      registre @tool + schéma unique (source du prompt ET du routage)
    fs.py            read_file(offset,limit) write_file edit_file(unique) multi_edit
    search.py        grep, glob
    shell.py         bash borné, timeout, troncature tête+queue, cwd explicite
  ui.py              rendu plain / rich / json, détection TTY, diff coloré
tests/               pytest : unitaires (aucun serveur) + intégration marquée slow
docs/                architecture.md tools.md protocole.md skills.md migration-v2-v3.md
examples/            calculatrice/, asteroid_dodge/   (déplacés)
```

Trois changements structurants :

1. **`protocol.py` isolé et pur.** Le (dé)codage des outils ne touche pas au réseau : on peut
   le tester exhaustivement, y compris sur les cas pathologiques (contenu contenant
   `</tool_calls>`, entités, indentation, très gros payloads). C'est ce qui empêche C1 de
   revenir.
2. **Registre d'outils = source unique.** Chaque outil déclare son schéma (nom, paramètres,
   types, description) une fois. Le system prompt est **généré** depuis ce registre. Plus de
   drift entre ce que le prompt annonce et ce que le routeur accepte (aujourd'hui,
   `write_file(raw=…)` et `edit_file(old=…)` sont acceptés en silence par le routeur mais
   absents du prompt).
3. **Rendu séparé du protocole.** Le texte envoyé au modèle (`llm`-facing) et l'affichage
   humain (`ui`) sont deux fonctions distinctes. Ça corrige C3 et ça permet `--plain`
   (pipes, CI) et `--json` (events NDJSON, scripting, intégration Hermes).

### 5.5 Décisions ouvertes

À trancher avant de coder la phase 3. Ma recommandation est en gras.

| # | Décision | Options | Recommandation |
|---|---|---|---|
| D1 | Protocole d'appel d'outils | (a) tool-calling **natif** OpenAI + `--jinja` ; (b) XML robuste avec CDATA ; (c) hybride avec détection de capacité | **(c)** : natif si le serveur l'annonce, repli XML/CDATA sinon. Le module `protocol.py` implémente les deux et un test de capacité décide. Raison : llama.cpp + Qwen3 supportent `tools` nativement — on supprime la classe de bugs C1 pour le chemin nominal, sans perdre les serveurs/modèles qui n'ont pas de tool-calling. |
| D2 | Mode par défaut sans argument | (a) REPL ; (b) afficher `--help` | **(a)** REPL, avec `-p` pour le one-shot. Aligné sur Hermes, claude-code, qwen-code. |
| D3 | Isolation | (a) aucune, assumée ; (b) sandbox opt-in `--sandbox` (écritures confinées) ; (c) sandbox par défaut | **(b)** : `--sandbox <dir>` refuse tout chemin absolu et tout `..` sortant. Défaut = comportement actuel + suppression de `base_dir`/`projects_dir` trompeurs. |
| D4 | Licence | MIT / Apache-2.0 | **MIT** (le plus permissif, cohérent avec les autres projets de l'auteur). |
| D5 | Nom du paquet PyPI / commande | `nikoforge` | **`nikoforge`**, console_script `nikoforge`, module `nikoforge`. |
| D6 | Config TOML vs YAML vs JSON | — | **TOML** (`~/.config/nikoforge/config.toml`), lisible, standard, commentable, sans dépendance lourde. |

### 5.6 Catalogue d'améliorations (au-delà de la refonte de base)

Classé par rapport valeur/effort. *✓ = retenu pour la v3.0 dans la roadmap.*

**Gros gains**

- ✓ `doctor` — diagnostic complet de l'installation (voir 5.2).
- ✓ **Checkpoint / undo** : avant chaque écriture, snapshot du fichier dans
  `~/.local/state/nikoforge/checkpoints/` → `/undo` restaure. Un agent local qui casse un
  fichier *doit* pouvoir revenir en arrière. C'est la fonctionnalité la plus rassurante à
  faible coût.
- ✓ **Diff affiché à chaque édition** (unified diff coloré) + `--dry-run`.
- ✓ **Sessions persistantes JSONL** append-only → `/resume`, `-c`, `--list-sessions`,
  export markdown. Aujourd'hui il faut penser à `--save-context mon.json` avant de fermer.
- ✓ **Compaction LLM réelle** avec conservation stricte : system + tâche initiale + K derniers
  échanges. (Corrige C7.)
- ✓ **Truncation intelligente** des sorties : tête+queue, texte complet écrit sur disque,
  chemin renvoyé au modèle. (Corrige C6 sans perdre d'information.)
- ✓ **Tokens réels** via `usage` du serveur au lieu de `len // 4`. (Corrige C7b.)
- ✓ **`enable_thinking=false` + `stop` sur la balise de fermeture** pour Qwen3 : gain de
  contexte et de latence immédiat. (Corrige C4.)
- ✓ **`AGENTS.md` / `CLAUDE.md` honorés** : lus dans le workdir et injectés. Convention de
  facto de tout l'écosystème ; le projet en a déjà un, qui est en plus faux (C15).
- ✓ **Skills réellement chargés** (`/skill <nom>`, découverte par glob, injection à la
  demande). (Corrige C12.)
- ✓ **Politique d'approbation par outil** : `read`/`grep`/`glob` libres, `write`/`edit`
  autonomes ou confirmés, `bash` confirmé par défaut. (Corrige C9.)

**Confort**

- ✓ `--plain` (sans emoji, sans couleurs) et `--json` (NDJSON d'événements) — le README
  revendique « intégration Hermes » : c'est le prérequis.
- ✓ Ctrl+C = **arrêt du tour**, pas du process (aujourd'hui `KeyboardInterrupt` tue le REPL).
- ✓ `--version`, `--print-config`, `--print-system-prompt`.
- ✓ Barre de statut non redondante, coin de boîte corrigé (C13).
- ✓ Message clair + commande suggérée si le serveur est absent (B2).
- ✓ Backlog des commandes slash : `/diff`, `/undo`, `/save`, `/skills`.

**Plus tard (hors v3.0)**

- Mode *plan* : l'agent écrit un plan markdown dans `.nikoforge/plans/` avant d'agir.
- Parallélisation des appels d'outils indépendants.
- `web_fetch` / `web_search` optionnels.
- `todo_write` : plan visible en cours de tâche.
- Mode multi-agents (délégation à un sous-agent).
- Client MCP.
- TUI (textual) / rôle `run_tests`.
- Benchmark local : temps et tokens par modèle pour un même prompt.
- Packaging AUR / snap / Nix.
- Support vision si le modèle est multimodal.

### 5.7 Ce qu'on supprime sans regret

| Supprimé | Raison |
|---|---|
| `run.py` | débris de sortie de modèle |
| `run.sh`, `run_test.sh` | cassés, remplacent par rien (`nikoforge` suffit) |
| `test.py`, `test.txt`, `xmltest.py` | débris |
| `bonjour.py`, `hello.py` (0 o), `index.html` | débris |
| `test_parser.py`, `test_tools.py` | scripts d'affichage sans assertions → remplacés par `tests/` |
| `_parse_tool_params` (39 l.) | code mort |
| `paths.projects_dir`, `paths.logs_dir` | config non implémentée |
| `config.example.json` | remplacé par les défauts en dur + `--print-config` |
| les démos en racine | → déplacées dans `examples/` |

---

## 6. Périmètre de la v3.0

**Dans le périmètre** : axes A→F, les 15 corrections de bugs, les décisions D1-D6,
les items « gros gains », `--plain`/`--json`, CI verte, docs réécrites, `examples/`.

**Hors périmètre** (backlog 3.1+) : plan mode, parallélisation, MCP, web tools, TUI,
multi-agents, vision, packaging distro, benchmark.

**Non négociable** : aucun merge sur `main` sans `pytest` vert + `ruff` + `mypy` propres.

---

## 7. Risques

| Risque | Parade |
|---|---|
| D1 : le tool-calling natif se comporte mal sur certains templates Qwen | le repli XML/CDATA est implémenté dans tous les cas ; test de capacité au démarrage, surchargeable par config |
| La compaction LLM coûte un appel de plus par compaction | seuil en tokens réels, compaction seulement au-delà de 80 % ; c'est un coût rare, et il remplace une corruption certaine |
| Le refactor `tools/` en registre casse la compatibilité des prompts déjà écrits | `prompt.md` en fichier + génération depuis le registre ; garder l'ancien nom des outils (`read_file`, `write_file`, `edit_file`, `bash`, `list_files`) |
| `--sandbox` gêne un usage légitime (agent qui doit sortir du dossier) | opt-in, jamais par défaut |
| Fiabilité des tests sans serveur LLM | tous les tests unitaires mockent le client ; un seul test d'intégration `slow` optionnel |
