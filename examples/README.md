# Exemples

Projets générés **par NikoForge lui-même**, conservés comme preuve de fonctionnement.
Ils ne font pas partie du produit et ne sont pas testés par la suite `tests/`.

| Projet | Description | Dépendance |
|---|---|---|
| `calculatrice/` | Calculatrice en ligne de commande (4 opérations, gestion de la division par zéro) | aucune |
| `asteroid_dodge/` | Jeu d'arcade : esquiver des astéroïdes | `pygame` |

Pour les lancer, se placer dans le dossier du projet :

```bash
cd examples/calculatrice && python main.py
cd examples/asteroid_dodge && python main.py
```

Ces dossiers servaient aussi de dépôt de test pour l'agent — c'est pourquoi ils étaient
auparavant à la racine, au milieu du code source. Regroupés ici, la racine ne contient plus
que les fichiers du produit.
