# Instructions pour les agents NikoForge

Ce fichier contient les instructions importantes pour tous les agents qui utilisent NikoForge.

## Principes fondamentaux

1. **Comprendre avant d'agir** - Toujours lire les fichiers existants avant de les modifier
2. **Petits changements itératifs** - Faire des modifications progressives et tester
3. **Expliciter** - Expliquer ce que tu fais et pourquoi
4. **Gérer les erreurs** - Propager les erreurs clairement, ne pas masquer
5. **Respecter la structure** - Suivre les conventions du projet existant

## Format des appels d'outils

Quand tu dois utiliser un outil, réponds dans ce format exact :

```
[outil: nom_outil]
paramètres...
```

Exemples :

```
[outil: read_file]
{"path": "src/main.py"}

[outil: write_file]
{"path": "src/utils.py", "content": "def hello():\n    print('Hello')"}

[outil: bash]
{"command": "python -m pytest tests/"}

[outil: list_files]
{"path": "src"}
```

## Bonnes pratiques de coding

- Toujours vérifier si un fichier existe avant de le lire
- Créer les répertoires parents si nécessaire
- Utiliser des noms de fichiers et variables clairs
- Ajouter des commentaires pour le code complexe
- Gérer les exceptions de manière appropriée
- Tester les commandes avant de les exécuter

## Gestion de l'erreur

- Vérifier les codes de retour des commandes
- Lire stderr pour les messages d'erreur
- Propager les erreurs avec des messages clairs
- Ne pas ignorer silencieusement les erreurs

## Priorité des tâches

1. Lis tous les fichiers pertinents
2. Comprends la structure du projet
3. Propose un plan d'action
4. Implémente les changements
5. Teste les modifications
6. Documente si nécessaire

## Quand demander de l'aide

- Si la demande n'est pas claire
- Si plusieurs approches sont possibles
- Si une modification pourrait être risquée
- Si tu as besoin de clarifications sur les préférences de l'utilisateur

## Workflow typique

1. Analyser la demande
2. Lister les fichiers concernés
3. Lire les fichiers existants
4. Proposer un plan
5. Implémenter les changements
6. Tester
7. Documenter

---

Révise ce fichier régulièrement pour améliorer les directives.