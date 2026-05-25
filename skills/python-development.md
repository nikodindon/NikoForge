# Skill: Python Development

Directives et meilleures pratiques pour le développement Python avec NikoForge.

## Structure de projet Python

```
project/
├── src/
│   ├── __init__.py
│   └── module.py
├── tests/
│   ├── __init__.py
│   └── test_module.py
├── requirements.txt
├── setup.py ou pyproject.toml
└── README.md
```

## Bonnes pratiques

1. **Type hints** - Utiliser les annotations de type pour les fonctions
2. **Docstrings** - Documenter les fonctions et classes avec des docstrings
3. **PEP 8** - Suivre les conventions de code Python
4. **Tests** - Écrire des tests unitaires pour le code important
5. **Virtual environments** - Toujours utiliser un venv pour les dépendances

## Exemples de code

```python
from typing import List, Dict, Optional

def process_data(items: List[Dict[str, any]]) -> Optional[Dict[str, any]]:
    """
    Traite une liste d'items et retourne un résultat agrégé.

    Args:
        items: Liste d'items à traiter

    Returns:
        Dictionnaire agrégé ou None si erreur
    """
    try:
        # Implémentation
        pass
    except Exception as e:
        print(f"Erreur: {e}")
        return None
```

## Dépendances

- Utiliser `requirements.txt` pour les dépendances simples
- Utiliser `pyproject.toml` pour les projets plus complexes
- Préciser les versions quand nécessaire (ex: `numpy>=1.20.0`)

## Tests

- Utiliser `pytest` pour les tests
- Placer les tests dans `tests/`
- Nommer les fichiers de test avec `test_` préfixe

## Linting et formattage

- Utiliser `black` pour le formattage automatique
- Utiliser `flake8` ou `pylint` pour le linting
- Configurer les ignores dans `setup.cfg` ou `.flake8`

## Gestion des erreurs

- Toujours gérer les exceptions
- Logger les erreurs avec des messages clairs
- Propager les exceptions critiques

## Performance

- Éviter les boucles imbriquées complexes
- Utiliser les comprehensions quand approprié
- Profiler si nécessaire avec `cProfile`

---

Ce skill peut être chargé automatiquement quand l'agent travaille sur un projet Python.