"""
Point d'entrée principal de NikoForge
"""

import argparse
import sys
import time
from pathlib import Path
from datetime import datetime

# Ajouter le répertoire courant au path
sys.path.insert(0, str(Path(__file__).parent))

from core.agent import Agent
from core.ui import NikoForgeUI


def main():
    parser = argparse.ArgumentParser(
        description="NikoForge - Agent de coding local",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python nikoforge.py "Crée-moi un script Python qui analyse des logs"
  python nikoforge.py -i
  python nikoforge.py --help
        """
    )

    parser.add_argument(
        "task",
        nargs="?",
        help="Tâche à accomplir en langage naturel"
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Mode interactif avec confirmation à chaque étape"
    )

    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Chemin vers le fichier de configuration (défaut: config.json)"
    )

    parser.add_argument(
        "--save-context",
        help="Sauvegarde le contexte dans un fichier"
    )

    parser.add_argument(
        "--load-context",
        help="Charge le contexte depuis un fichier"
    )

    args = parser.parse_args()

    # Afficher le logo
    NikoForgeUI.clear_screen()
    NikoForgeUI.print_logo()

    # Initialiser l'agent
    try:
        agent = Agent(config_path=args.config)
        NikoForgeUI.print_header(
            model=agent.config['llm']['model'],
            base_url=agent.config['llm']['base_url'],
            max_tokens=agent.config['context']['max_tokens']
        )
    except Exception as e:
        NikoForgeUI.print_error(f"Erreur d'initialisation: {e}")
        sys.exit(1)

    # Charger le contexte si demandé
    if args.load_context:
        try:
            agent.load_context(args.load_context)
            NikoForgeUI.print_success(f"Contexte chargé depuis {args.load_context}")
        except Exception as e:
            NikoForgeUI.print_error(f"Erreur chargement contexte: {e}")
            sys.exit(1)

    # Mode interactif ou direct
    if args.interactive:
        NikoForgeUI.print_welcome()

        start_time = time.time()

        while True:
            try:
                task = NikoForgeUI.print_prompt()

                if not task:
                    continue
                if task.lower() in ['quit', 'exit', 'q']:
                    NikoForgeUI.print_success("Au revoir !")
                    break

                if task.lower() == 'stats':
                    stats = agent.get_stats()
                    NikoForgeUI.print_stats(stats)
                    continue

                if task.lower() == 'clear':
                    NikoForgeUI.clear_screen()
                    NikoForgeUI.print_logo()
                    NikoForgeUI.print_header(
                        model=agent.config['llm']['model'],
                        base_url=agent.config['llm']['base_url'],
                        max_tokens=agent.config['context']['max_tokens']
                    )
                    continue

                if task.lower() == 'help':
                    NikoForgeUI.print_help()
                    continue

                # Exécuter la tâche
                NikoForgeUI.print_task(task)
                agent.run(task, interactive=True)

                # Afficher la barre de statut après chaque tâche
                elapsed_time = time.time() - start_time
                stats = agent.get_stats()
                NikoForgeUI.print_status_bar(
                    model=agent.config['llm']['model'],
                    current_tokens=stats['context_stats']['estimated_tokens'],
                    max_tokens=agent.config['context']['max_tokens'],
                    iteration=stats['iteration'],
                    elapsed_time=elapsed_time
                )

            except KeyboardInterrupt:
                NikoForgeUI.print_success("Au revoir !")
                break
    else:
        # Mode direct
        if not args.task:
            NikoForgeUI.print_info("Tu dois fournir une tâche ou utiliser le mode interactif (-i)")
            parser.print_help()
            sys.exit(1)

        start_time = time.time()
        NikoForgeUI.print_task(args.task)
        result = agent.run(args.task, interactive=False)

        # Afficher la barre de statut
        elapsed_time = time.time() - start_time
        stats = agent.get_stats()
        NikoForgeUI.print_status_bar(
            model=agent.config['llm']['model'],
            current_tokens=stats['context_stats']['estimated_tokens'],
            max_tokens=agent.config['context']['max_tokens'],
            iteration=stats['iteration'],
            elapsed_time=elapsed_time
        )

        NikoForgeUI.print_completion()
        NikoForgeUI.print_stats(stats)

    # Sauvegarder le contexte si demandé
    if args.save_context:
        try:
            agent.save_context(args.save_context)
            NikoForgeUI.print_success(f"Contexte sauvegardé dans {args.save_context}")
        except Exception as e:
            NikoForgeUI.print_error(f"Erreur sauvegarde contexte: {e}")


if __name__ == "__main__":
    main()