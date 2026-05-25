"""
Point d'entrée principal de NikoForge
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Ajouter le répertoire courant au path
sys.path.insert(0, str(Path(__file__).parent))

from core.agent import Agent


def main():
    parser = argparse.ArgumentParser(
        description="NikoForge - Agent de coding local",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python nikoforge.py "Crée-moi un script Python qui analyse des logs"
  python nikoforge.py --interactive
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

    # Vérifier si llama-server est accessible
    print("🔥 NikoForge - Agent de coding local")
    print("=" * 50)

    # Initialiser l'agent
    try:
        agent = Agent(config_path=args.config)
        print(f"✓ Agent initialisé")
        print(f"  - Modèle: {agent.config['llm']['model']}")
        print(f"  - Base URL: {agent.config['llm']['base_url']}")
        print(f"  - Max tokens: {agent.config['context']['max_tokens']}")
    except Exception as e:
        print(f"✗ Erreur d'initialisation: {e}")
        sys.exit(1)

    # Charger le contexte si demandé
    if args.load_context:
        try:
            agent.load_context(args.load_context)
            print(f"✓ Contexte chargé depuis {args.load_context}")
        except Exception as e:
            print(f"✗ Erreur chargement contexte: {e}")
            sys.exit(1)

    # Mode interactif ou direct
    if args.interactive:
        print("\n📝 Mode interactif activé")
        print("   Tape ta tâche ci-dessous (ou 'quit' pour sortir)\n")

        while True:
            try:
                task = input("❓ NikoForge> ").strip()

                if not task:
                    continue
                if task.lower() in ['quit', 'exit', 'q']:
                    print("👋 Au revoir !")
                    break

                print()
                agent.run(task, interactive=True)

            except KeyboardInterrupt:
                print("\n👋 Au revoir !")
                break
    else:
        # Mode direct
        if not args.task:
            parser.print_help()
            print("\n⚠️  Tu dois fournir une tâche ou utiliser le mode interactif (-i)")
            sys.exit(1)

        print(f"\n📋 Tâche: {args.task}\n")
        result = agent.run(args.task, interactive=False)

        print("\n" + "=" * 50)
        print("✓ Terminé !")

        # Afficher les stats
        stats = agent.get_stats()
        print(f"\n📊 Statistiques:")
        print(f"  - Itérations: {stats['iteration']}")
        print(f"  - Messages: {stats['context_stats']['total_messages']}")
        print(f"  - Tokens estimés: {stats['context_stats']['estimated_tokens']}")
        if stats['context_stats']['compaction_count'] > 0:
            print(f"  - Compactions: {stats['context_stats']['compaction_count']}")

    # Sauvegarder le contexte si demandé
    if args.save_context:
        try:
            agent.save_context(args.save_context)
            print(f"✓ Contexte sauvegardé dans {args.save_context}")
        except Exception as e:
            print(f"✗ Erreur sauvegarde contexte: {e}")


if __name__ == "__main__":
    main()