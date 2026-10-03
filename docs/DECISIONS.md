# Décisions d'architecture — NikoForge v3.0

> Journal des arbitrages. Chaque entrée est courte, datée, et indique explicitement ce qui
> est **tranché** et ce qui est **proposé en attente de confirmation**.
> Contexte et alternatives détaillées : [`REFONTE.md`](REFONTE.md) §5.5.

Format : `D<n> — titre` · statut (`TRANCHÉ` / `PROPOSÉ`) · décision · raison · conséquences.

---

## D1 — Protocole d'appel d'outils

**Statut : TRANCHÉ (2026-10-03) — mesuré sur un serveur réel, implémenté en phase 3**

**Décision** : hybride à détection de capacité.

- Détection sur ``GET /props`` → ``chat_template_caps.supports_tools``.
- Si vrai → **tool-calling natif** (champ ``tools``, réponse en ``tool_calls`` structurés).
- Sinon, ou si le serveur renvoie une erreur en refusant ``tools`` → **protocole textuel**
  balisé, contenu encodé en **CDATA**, analysé par une machine à états (jamais par expression
  régulière).
- Les deux formes sont **toujours acceptées en lecture** : même en mode natif, un bloc balisé
  présent dans le contenu est décodé et retiré du texte. Un modèle ou un serveur qui mélange
  les deux ne casse rien.
- ``llm.protocol`` permet de forcer ``auto`` (défaut), ``native`` ou ``text``. Un mode forcé ne
  se replie pas : l'erreur est explicite.

**Mesures qui ont tranché** (serveur ``llama-server``, modèle ``Ornith-1.5-35B-IQ2_M``) :

```
GET /v1/models   → "capabilities": ["completion"]        ← FAUX, n'indique pas les outils
GET /props       → chat_template_caps.supports_tools: true
                   supports_parallel_tool_calls: true
                   supports_system_role: true
POST /v1/chat/completions avec tools=… → HTTP 200
                   tool_calls: [{"name": "list_files", "arguments": "{\"path\":\".\"}"}]
```

**Raison** : le champ ``capabilities`` de ``/v1/models`` a menti. Une détection fondée sur lui
aurait conclu « pas d'outils » et fait prendre le chemin textuel — donc la classe de bugs C1 —
alors que le serveur gère parfaitement les appels natifs. ``/props`` est la source fiable.
Le repli textuel reste indispensable : le projet revendique de tourner sur n'importe quel
serveur compatible OpenAI, et ceux qui n'ont pas de ``tools`` existent.

**Conséquences** :
- ``protocol.py`` est pur (aucune entrée/sortie) et couvert par 103 tests, dont l'aller-retour
  encodeur/décodeur sur des contenus piégés (``</tool>``, ``</param>``, ``</tool_calls>``,
  indentation, entités, CDATA imbriqué, 100 000 caractères).
- ``LLM`` bascule automatiquement sur un refus de ``tools`` et mémorise le choix pour la
  session (testé).
- La classe de bugs C1a ne peut plus se produire sur le chemin natif, et plus sur le chemin
  textuel non plus : dans un CDATA, un ``</tool>`` du contenu est invisible pour le découpage.

---

## D2 — Comportement de `nikoforge` sans argument

**Statut : PROPOSÉ — implémenté en phase 2, à confirmer**

**Décision proposée** : REPL interactif par défaut ; `-p/--print "prompt"` pour le one-shot.

**Raison** : aligne le projet sur Hermes, claude-code et qwen-code. Un agent de coding
s'utilise majoritairement en conversation continue ; exiger `-i` pour ça est un frottement
inutile. Le one-shot reste accessible et scriptable via `-p`.

**Mis en œuvre ainsi (phase 2)** :
- `nikoforge` seul ouvre le REPL ; `nikoforge -p "..."` exécute une tâche et rend la main.
- `-i/--interactive` est toujours **accepté** mais sans effet, avec une note sur `stderr` :
  la commande documentée de la v2 continue de marcher.
- `nikoforge "tâche"` (sans `-p`) fonctionne aussi, avec une note de dépréciation.
  Contrepartie assumée : un mot isolé est *toujours* lu comme un prompt, donc une sous-commande
  mal orthographiée devient une tâche au lieu d'une erreur (test `known_issue` en phase 5).

**Conséquences** : à documenter dans `docs/migration-v2-v3.md` (fait).

---

## D3 — Isolation des écritures

**Statut : PROPOSÉ (en attente de confirmation)**

**Décision proposée** : aucune isolation par défaut (comportement actuel assumé) **plus**
`--sandbox <dir>` opt-in, qui refuse tout chemin absolu et tout `..` sortant de la racine
de sandbox.

**Raison** : l'utilisateur est mono-utilisateur sur sa propre machine, et se voir refuser
l'accès à `~/models` ou `~/projets` serait pénible. En revanche, `base_dir` et
`projects_dir` laissent croire à un confinement qui n'existe pas (bug C13/C14) : soit on le
fournit pour de vrai, soit on retire la promesse. Le milestone retient les deux :
`--sandbox` réellement appliqué, et `base_dir`/`projects_dir` supprimés de la config.

**Conséquences** :
- `_resolve_path` doit passer par une fonction unique qui applique la politique
  (`Path.resolve()` puis vérification de préfixe, pour résister aux symlinks et à `..`).
- Test obligatoire : `--sandbox /tmp/sb` avec une écriture vers `/etc/passwd` → refus explicite,
  rien sur le disque.
- La politique d'approbation par outil (D3bis, phase 3) reste indépendante de l'isolation.

---

## D4 — Licence

**Statut : PROPOSÉ**

**Décision proposée** : MIT.

**Raison** : le plus permissif, sans friction pour la réutilisation, cohérent avec la
philosophie du projet et les autres dépôts publics de l'auteur.

**Conséquences** : `LICENSE` à la racine en phase 1 ; mention dans `pyproject.toml`.

---

## D5 — Nom du paquet et de la commande

**Statut : TRANCHÉ**

**Décision** : distribution `nikoforge`, module Python `nikoforge`, commande `nikoforge`.
`python -m nikoforge` fonctionne aussi.

**Raison** : le nom est déjà celui du dépôt et du fichier d'entrée ; rien à expliquer.
`console_scripts` fournit la commande, ce qui supprime le `python nikoforge.py` actuel
(et la confusion avec `run.py`, qui est supprimé en phase 1).

**Conséquences** : `core/` devient `nikoforge/` (paquet installable) en phase 2.

---

## D6 — Format de configuration

**Statut : TRANCHÉ — implémenté en phase 2**

**Décision** : TOML, à `~/.config/nikoforge/config.toml` (surchargé par
`$NIKOFORGE_CONFIG`). Le fichier est **optionnel** : toutes les valeurs par défaut existent
en dur dans le code, `nikoforge --print-config` les affiche.

**Raison** : lisible, commentable, standard, sans dépendance lourde (`tomllib` est dans la
stdlib depuis Python 3.11 — cohérent avec le plancher 3.11 de la CI). Le JSON actuel impose
une étape d'édition manuelle qui bloque un utilisateur sur deux au premier lancement (bug B1).

**Mis en œuvre ainsi (phase 2)** :
- `nikoforge/config.py` : dataclasses gelées, défauts complets, précédence
  `défauts < TOML < environnement < CLI`.
- 10 variables `NIKOFORGE_*`. Une clé ou une section inconnue est **refusée** avec la liste
  des clés valides — pas de faute de frappe silencieuse.
- `render_toml` produit un TOML commenté et complet, ré-analysable à l'identique
  (`test_render_toml_round_trip`). `write_config` écrit de façon atomique.
- TOML n'ayant pas de valeur nulle, `llm.timeout = 0` signifie « pas de limite » (et non
  `null`, qui n'existe pas dans le format).
- `nikoforge init` écrit le fichier ; `--print-config` l'affiche sans rien écrire.
- `config.example.json` supprimé, section `paths` supprimée (jamais implémentée, bug C12).

**Conséquences** : la note `docs/migration-v2-v3.md` contient la traduction d'un
`config.json` de la v2 vers le TOML.

---

## Journal

| Date | Entrée |
|---|---|
| 2026-10-03 | D4, D5, D6 proposés/retenus sur recommandation. D1, D2, D3 proposés — **en attente de confirmation de l'auteur** avant d'attaquer la phase 3. |
