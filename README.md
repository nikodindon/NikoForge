# 🔥 NikoForge

**Agent de coding local.** Il transforme une consigne en langage naturel en fichiers et en
commandes, en utilisant un modèle que tu fais tourner chez toi (llama-server ou tout serveur
compatible OpenAI).

> ⚠️ **Branche `dev` — refonte v3.0 en cours.** `main` reste la v2.0 (fonctionnelle, mais
> 18 défauts reproduits dont un qui empêche le démarrage sans `config.json`).
> 📄 [`docs/REFONTE.md`](docs/REFONTE.md) · 🗺️ [`ROADMAP.md`](ROADMAP.md) ·
> ⚖️ [`docs/DECISIONS.md`](docs/DECISIONS.md)

---

## Installer

```bash
uv tool install git+https://github.com/nikodindon/NikoForge.git@dev
# ou
pipx install git+https://github.com/nikodindon/NikoForge.git@dev
```

Démarre ensuite un serveur d'inférence — par exemple llama-server :

```bash
llama-server -m /chemin/vers/mon-modele.gguf --port 8080 -c 65536 --jinja
```

Puis vérifie que tout est en place :

```
$ nikoforge doctor
nikoforge 3.0.0.dev0 — prêt
serveur http://127.0.0.1:44421/v1 (port 44421) · config (valeurs par défaut, aucun fichier)
────────────────────────────────────────────────────────────────────
✔ python         3.12.3
✔ paquet         nikoforge 3.0.0.dev0
✔ config         aucun fichier, valeurs par défaut (/tmp/nf_demo_home/.config/nikoforge/config.toml absent)
✔ serveur        http://127.0.0.1:44421/v1 (25 ms) — 1 modèle(s)
✔ modèle         Qwen3.6-35B-A3B-UD-IQ3_S.gguf (découvert)
✔ contexte       32768 tokens (serveur : 65536)
✔ outils         read_file, write_file, edit_file, bash, list_files
⚠ skills         1 présent(s), chargement en phase 4 : python-development
✔ workdir        /home/niko/projects/NikoForge
✔ stockage       /tmp/nf_demo_home/.local/share/nikoforge · /tmp/nf_demo_home/.local/state/nikoforge

Tout est opérationnel (avertissements non bloquants ci-dessus).
```

*(sortie réelle, recopiée telle quelle ; le serveur était un serveur de test qui annonce ce
modèle. Le port, le nom du modèle, le `workdir` et les chemins XDG varient selon la machine.)*

`doctor` sort en code 0 si tout va bien, et en **1** sinon — il liste alors ce qui bloque et
la commande à copier pour corriger. Quand le serveur ne répond pas :

```
$ nikoforge -p "test"
✖ serveur injoignable : http://127.0.0.1:8080/v1 — connexion impossible ([Errno 111] Connection refused)
  Aucun serveur n'écoute sur http://127.0.0.1:8080/v1/models.

  Lancez le serveur, par exemple :
    llama-server -m /chemin/vers/modele.gguf \
      --host 127.0.0.1 --port 8080 -c 65536 --jinja \
      -ngl 999 --flash-attn on

  Diagnostic complet : nikoforge doctor
$ echo $?
3
```

**Aucun fichier de configuration n'est nécessaire.** Les valeurs par défaut visent
`http://127.0.0.1:8080/v1` et le nom du modèle est lu sur `GET /v1/models`. `nikoforge init`
écrit une configuration complète et commentée dans `~/.config/nikoforge/config.toml` si tu
veux figer des valeurs :

```
$ nikoforge init
Configuration NikoForge — écriture dans /tmp/nf_init_home/.config/nikoforge/config.toml

✔ serveur joignable : http://127.0.0.1:44421/v1 (24 ms)
✔ modèle retenu : Qwen3.6-35B-A3B-UD-IQ3_S.gguf

✔ configuration écrite : /tmp/nf_init_home/.config/nikoforge/config.toml

Prochaines étapes :
  nikoforge doctor            # vérifie que tout est en place
  nikoforge -p "bonjour"      # une tâche, en une commande
  nikoforge                   # ou directement le mode interactif
```

---

## Utiliser

```
nikoforge                              # mode interactif (défaut)
nikoforge -p "analyse les logs de /var/log"   # une tâche, puis quitter
nikoforge --cwd ~/projets/truc         # travailler dans un autre dossier
nikoforge --model un-autre-modele      # surcharger ponctuellement
nikoforge init                         # écrire la configuration
nikoforge doctor                        # diagnostiquer l'installation
nikoforge --print-config                # configuration effective, commentée
nikoforge --print-system-prompt         # prompt envoyé au modèle (debug)
nikoforge --version
```

Une tâche, sur le vrai serveur de développement (llama-server, modèle 35 B, protocole
d'appels d'outils **natif** détecté automatiquement sur `/props`) :

```
$ nikoforge --cwd /tmp/demo --max-iterations 6 \
    -p "Cree un fichier hello.py qui affiche Bonjour NikoForge, puis execute-le pour verifier."

📋 Tâche: Cree un fichier hello.py qui affiche Bonjour NikoForge, puis execute-le pour verifier.

──────────────────────────────────────────────────────────────────────

 ⚕ /mnt/data/sdc2/models/Ornith-1.5-35B-IQ2_M.gguf │ ctx 1245/32768 │ [░░░░░░░░░░░░░░░░░░░░] 3.8% │ 3 itérations │ ⏲ 16.7s
──────────────────────────────────────────────────────────────────────
C'est fait ! ✅

- ✅ `hello.py` créé avec `print("Bonjour NikoForge")`
- ✅ Exécuté avec succès
- Sortie : `Bonjour NikoForge`

📊 Statistiques:
  • Itérations: 3
  • Messages: 6
  • Tokens estimés: 1245

✓ Terminé !
```

*(sortie réelle, recopiée telle quelle. Le fichier créé contient bien `print("Bonjour
NikoForge")` et son exécution affiche `Bonjour NikoForge`.)*

### Protocole d'appel d'outils

NikoForge utilise le **tool-calling natif** de l'API OpenAI quand le serveur l'annonce, et
bascule sinon sur un protocole textuel balisé dont le contenu est encodé en CDATA. Les deux
formes sont acceptées en lecture, y compris mélangées.

La détection se fait sur `GET /props` → `chat_template_caps.supports_tools`, et **non** sur le
champ `capabilities` de `GET /v1/models` : mesuré sur un serveur réel, celui-ci annonce
`["completion"]` tout en gérant parfaitement `tools`. Forçable par `llm.protocol`
(`auto` | `native` | `text`).

### Codes de sortie

| Code | Signification |
|---|---|
| `0` | succès |
| `1` | échec d'exécution (tâche sans résultat, ou `doctor` a trouvé un bloquant) |
| `2` | erreur d'usage ou de configuration (argument invalide, TOML illisible…) |
| `3` | serveur injoignable ou aucun modèle disponible |

### Commandes du mode interactif

```
quit / exit / q     quitter
stats               statistiques de la session
clear               effacer l'écran
help                cette aide
```

### Configurer

Trois façons, de la plus durable à la plus ponctuelle. La précédence va des valeurs par
défaut vers la ligne de commande :

```
défauts  <  ~/.config/nikoforge/config.toml  <  variables d'environnement  <  arguments CLI
```

Variables reconnues : `NIKOFORGE_BASE_URL`, `NIKOFORGE_MODEL`, `NIKOFORGE_API_KEY`,
`NIKOFORGE_TEMPERATURE`, `NIKOFORGE_MAX_TOKENS`, `NIKOFORGE_TIMEOUT`, `NIKOFORGE_CONTEXT`,
`NIKOFORGE_MAX_ITERATIONS`, `NIKOFORGE_TOOL_TIMEOUT`, `NIKOFORGE_CONFIG`.

Une clé inconnue est refusée avec la liste des clés valides — pas de faute de frappe silencieuse :

```
$ echo '[llm]
max_token = 10' > /tmp/mauvais.toml && nikoforge -c /tmp/mauvais.toml --print-config
✖ configuration : clé inconnue dans [llm] : max_token. Clés valides : api_key, base_url, max_tokens, model, temperature, timeout
```

`nikoforge --print-config` affiche la configuration effective, complète et commentée — c'est
aussi un TOML valide, réutilisable tel quel :

```toml
# Configuration NikoForge.
#
# Genere par `nikoforge init`. Toutes les valeurs sont optionnelles :
# ce fichier peut etre supprime, les defauts du programme s'appliquent.
#
# Precedence : defauts < ce fichier < variables d'environnement < arguments CLI.

# Serveur d'inference (llama-server ou tout autre endpoint compatible OpenAI)
[llm]
# URL du serveur, terminee par /v1
base_url = "http://127.0.0.1:8080/v1"
# Nom du modele. Vide = decouvert via GET /v1/models
model = ""
# Cle d'API. Ignoree par llama-server, mais requise par le client
api_key = "sk-dummy"
# 0.0 = deterministe, 1.0 = creatif
temperature = 0.7
# Longueur maximale d'une reponse du modele
max_tokens = 8192
# Delai maximal en secondes. 0 = pas de limite
timeout = 300.0

# Budget de contexte et declenchement de la compaction
[context]
# Fenetre de contexte annoncee par le serveur
max_tokens = 32768
...
```

### Exemples de prompts

Voir [`docs/prompts.md`](docs/prompts.md).

---

## Étendre

### Structure du dépôt

```
nikoforge/
  __init__.py    version (source unique, lue par pyproject.toml)
  __main__.py    python -m nikoforge
  cli.py         arguments, sous-commandes, REPL, codes de sortie
  config.py      dataclasses, TOML, variables d'environnement, précédence
  server.py      découverte du serveur et du modèle (urllib, sans dépendance)
  doctor.py      diagnostic, contrôles et remèdes
  wizard.py      assistant `init`
  protocol.py    (dé)codage des appels d'outils + schéma des outils — pur, sans I/O
  llm.py         streaming, outils, raisonnement, reprises, erreurs nommées
  agent.py       boucle de la tâche, approbation, rendu des résultats
  context.py     historique, mesure réelle du contexte, compaction par le modèle
  tools.py       read_file, write_file, edit_file, bash, list_files
  prompt.py      prompt système (liste d'outils engendrée depuis protocol.py)
  ui.py          affichage terminal
tests/           416 tests, aucun serveur LLM requis
examples/        projets produits par l'agent (démonstration)
docs/            refonte, décisions, prompts, migration
```

### Développer

```bash
git clone -b dev https://github.com/nikodindon/NikoForge.git
cd NikoForge
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest     # 416 tests, ~1 min, aucun GPU requis
.venv/bin/ruff check .
.venv/bin/mypy
```

La suite de tests fonctionne **sans serveur LLM** : le client est simulé ou bien on lance
`tests/fake_server.py`, un vrai serveur HTTP qui parle l'API OpenAI (streaming SSE, outils
fragmentés, raisonnement, erreurs programmables). Les tests marqués `known_issue` documentent
un défaut identifié (« ce test passera au rouge quand le bug sera corrigé, il faudra alors
l'inverser ») — voir [`tests/README.md`](tests/README.md).

⚠️ Un faux serveur ne reproduit pas la validation faite par un **vrai** gabarit de chat. Un
défaut d'ordonnancement des messages (`docs/REFONTE.md` C18) n'a été trouvé qu'en exécutant
l'agent contre un `llama-server` réel. Un test d'intégration optionnel est prévu en phase 6.

### Ajouter un outil

Les outils sont pour l'instant des méthodes de `nikoforge/tools.py`, routées par
`Agent._execute_tool`. Un registre déclaratif (schéma unique, prompt système généré) arrive
en phase 4 — voir [`ROADMAP.md`](ROADMAP.md).

---

## Migration depuis la v2

`python nikoforge.py`, `config.json` et `requirements.txt` n'existent plus.
Voir [`docs/migration-v2-v3.md`](docs/migration-v2-v3.md).

---

## Licence

MIT — voir [`LICENSE`](LICENSE).

Créé par [@nikodindon](https://github.com/nikodindon).
« Parce que le futur du coding doit tourner chez soi. »
