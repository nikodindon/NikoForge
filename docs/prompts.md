# Exemples de prompts

Le modèle fait le travail ; la qualité de la consigne fait la différence. Ces exemples sont
classés du plus simple au plus ambitieux, et tous utilisent la forme recommandée `-p`.

## Découverte

```bash
nikoforge -p "liste les fichiers Python du projet et résume le rôle de chacun"
nikoforge -p "explique ce que fait ce projet, en 10 lignes"
nikoforge -p "quelles sont les dépendances déclarées ? y a-t-il des imports non déclarés ?"
```

## Écriture et modification

```bash
nikoforge -p "crée un fichier hello.py qui affiche 'Hello NikoForge!'"
nikoforge -p "lis README.md et écris un résumé dans SUMMARY.md"
nikoforge -p "dans hello.py, remplace 'Hello NikoForge!' par 'Bonjour!'"
nikoforge -p "ajoute des docstrings à toutes les fonctions de nikoforge/tools.py"
```

## Vérification

```bash
nikoforge -p "lance les tests et corrige ce qui échoue"
nikoforge -p "ce fichier contient-il des erreurs ? corrige-les et relance les tests"
```

## Création de projet

```bash
nikoforge -p "crée un script Python analyze_logs.py qui lit un fichier log passé en
argument et compte les lignes contenant 'ERROR'"

nikoforge -p "crée la structure d'un projet Python :
- un package src/
- un module main.py dans src/
- un requirements.txt
- un README.md
- un dossier tests/ avec un test vide"
```

## Multi-étapes

Pour une tâche longue, décrire les étapes explicitement donne de bien meilleurs résultats
qu'une consigne vague :

```bash
nikoforge -p "crée un outil de conversion de fichiers :

Étape 1 — structure
- package converter/
- converter/core.py (logique de conversion)
- converter/cli.py (interface en ligne de commande)
- tests/ avec pytest

Étape 2 — fonctionnalités
- convertir TXT vers JSON (un objet par ligne)
- convertir CSV vers JSON
- options --input et --output

Étape 3 — documentation
- README.md avec des exemples
- docstrings sur toutes les fonctions

Implémente étape par étape et lance les tests à chaque étape."
```

## Mode interactif

Le REPL est le mode par défaut — il conserve le contexte entre les tours, ce qui évite de
tout redécrire :

```
$ nikoforge

❓ NikoForge> crée un fichier test.py avec une fonction factorielle
❓ NikoForge> ajoute-lui une gestion d'erreur pour les entrées négatives
❓ NikoForge> lance-le pour vérifier
❓ NikoForge> corrige ce qui ne va pas
❓ NikoForge> stats
```

## Conseils

- **Dire quoi vérifier.** « lance les tests », « exécute le script », « relis le fichier après
  modification » : le modèle se corrige beaucoup mieux quand on lui demande de vérifier.
- **Donner le chemin.** `nikoforge --cwd ~/projets/mon-projet` évite les ambiguïtés.
- **Découper.** Une tâche par invocation est plus fiable qu'un prompt fourre-tout ; le budget
  d'itérations (20 par défaut, réglable par `--max-iterations`) se consomme vite.
- **Un modèle qui écrit est un modèle qui peut casser.** `git status` avant, `git diff` après.

> ⚠️ Les exemples de cette page n'ont pas été rejoués depuis la refonte : ils proviennent de
> la documentation de la v2. Le format des commandes est à jour, mais les résultats attendus
> ne sont pas garantis. Ils seront vérifiés en phase 6.
