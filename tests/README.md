# Tests NikoForge

## Philosophie de la phase 1 : tests « dorés » (golden tests)

Cette suite a été écrite **avant** la refonte, sur le code de la v2. Elle ne décrit donc pas
le comportement *souhaité* : elle **capture le comportement réel**, y compris ses défauts.

C'est volontaire. Sans filet, un refactor de 2 jours sur une boucle d'agent ne se distingue
pas d'une régression. Ces tests permettent de dire, à chaque étape de la phase 3 :

> ce qui a changé, c'est exactement ce que je voulais changer — et rien d'autre.

## Le marqueur `known_issue`

Les tests marqués `@pytest.mark.known_issue` documentent un bug **identifié et reproduit**
(voir [`docs/REFONTE.md`](../docs/REFONTE.md), identifiants `B*` et `C*`). Ils passent
aujourd'hui parce qu'ils affirment le comportement fautif.

Exemple : `test_edit_file_replaces_all_occurrences` affirme que les deux occurrences de
`x = 1` sont modifiées — parce que c'est ce que fait le code aujourd'hui (bug C5).
En phase 3, ce test sera **inversé** : il devra affirmer qu'une erreur est levée si le motif
n'est pas unique.

**Tout test `known_issue` doit disparaître ou être inversé à la fin de la phase 3.**
Compter les tests `known_issue` est donc un bon indicateur d'avancement :

```bash
pytest -m known_issue -q --collect-only | tail -1
```

## Lancement

```bash
python -m pytest              # toute la suite
python -m pytest -m known_issue    # uniquement les bugs documentés
python -m pytest -m "not known_issue"   # uniquement le comportement à préserver
```

Aucun serveur LLM n'est requis. Aucun fichier du dépôt n'est modifié : l'outil `Tools` est
toujours construit avec un `base_dir` temporaire.

## Organisation

| Fichier | Ce qui est couvert |
|---|---|
| `test_config.py` | `config.example.json` est valide et couvre toutes les clés lues par le code |
| `test_protocol_current.py` | l'extraction des appels d'outils, telle qu'implémentée en v2 |
| `test_tools.py` | `read_file`, `write_file`, `edit_file`, `list_files`, `bash`, `ToolResult` |
| `test_context.py` | `ContextManager` : historique, estimation, compaction, sauvegarde |
| `test_agent_loop.py` | boucle de l'agent et routage des outils |
| `test_cli.py` | point d'entrée en sous-processus (`--help`, absence de configuration) |

## Ce qui n'est pas testé ici (et pourquoi)

- **Les appels au modèle** : ils exigent un `llama-server` en marche. Ils arriveront en phase 6
  derrière le marqueur `integration`, désactivé par défaut.
- **L'affichage (`core/ui.py`)** : il imprime directement sur `sys.stdout` (méthodes statiques,
  aucun point d'injection). Il n'est pas testable sans le refactor de la phase 5, qui sépare
  le rendu de la logique.
