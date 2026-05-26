"""
Module UI pour NikoForge - Affichage stylisé et barre de statut
"""

import os
import sys
from typing import Optional


class NikoForgeUI:
    """Interface utilisateur stylisée pour NikoForge"""

    # ASCII art logo
    LOGO = """
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║   ███╗   ██╗███████╗██╗  ██╗██╗   ██╗██╗    ██████╗ ███████╗ ║
    ║   ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██║    ██╔══██╗██╔════╝ ║
    ║   ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║██║    ██████╔╝███████╗ ║
    ║   ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║██║    ██╔══██╗╚════██║ ║
    ║   ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝██║    ██║  ██║███████║ ║
    ║   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝    ╚═╝  ╚═╝╚══════╝ ║
    ║                                                              ║
    ║                    v2.0 - XML + Streaming                    ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """

    # Barre de séparation
    SEPARATOR = "─" * 70

    @staticmethod
    def clear_screen():
        """Efface l'écran"""
        os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def print_logo():
        """Affiche le logo NikoForge"""
        print(NikoForgeUI.LOGO)

    @staticmethod
    def print_header(model: str, base_url: str, max_tokens: int, version: str = "v2.0"):
        """Affiche l'en-tête avec les infos système"""
        print(f"╭{'─' * 68}╮")
        print(f"│{'NikoForge Agent ' + version:^68}│")
        print(f"├{'─' * 68}┤")
        print(f"│{'Modèle: ' + model:^68}│")
        print(f"│{'Base URL: ' + base_url:^68}│")
        print(f"│{'Max Context: ' + str(max_tokens) + ' tokens':^68}│")
        print(f"╰{'─' * 68}╮")

    @staticmethod
    def print_status_bar(
        model: str,
        current_tokens: int,
        max_tokens: int,
        iteration: int,
        elapsed_time: float
    ):
        """Affiche la barre de statut en bas comme Hermes"""
        # Calculer le pourcentage
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0

        # Créer la barre de progression
        bar_width = 20
        filled = int((percentage / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Formater le temps
        time_str = f"{elapsed_time:.1f}s" if elapsed_time < 60 else f"{elapsed_time/60:.1f}m"

        print(f"\n ⚕ {model} │ ctx {current_tokens}/{max_tokens} │ [{bar}] {percentage:.1f}% │ {iteration} itérations │ ⏲ {time_str}")
        print(NikoForgeUI.SEPARATOR)

    @staticmethod
    def print_welcome():
        """Affiche le message de bienvenue"""
        print("\n🎮 Bienvenue dans NikoForge !")
        print("   Tape ta tâche ci-dessous (ou 'quit' pour sortir)\n")
        print("   Commandes:")
        print("   • 'quit' ou 'exit' ou 'q' - Quitter")
        print("   • 'stats' - Afficher les statistiques")
        print("   • 'clear' - Effacer l'écran")
        print("   • 'help' - Afficher l'aide\n")

    @staticmethod
    def print_prompt():
        """Affiche le prompt interactif"""
        return input("❓ NikoForge> ").strip()

    @staticmethod
    def print_stats(stats: dict):
        """Affiche les statistiques"""
        print(f"\n📊 Statistiques:")
        print(f"  • Itérations: {stats['iteration']}")
        print(f"  • Messages: {stats['context_stats']['total_messages']}")
        print(f"  • Tokens estimés: {stats['context_stats']['estimated_tokens']}")
        if stats['context_stats']['compaction_count'] > 0:
            print(f"  • Compactions: {stats['context_stats']['compaction_count']}")

    @staticmethod
    def print_help():
        """Affiche l'aide"""
        print("\n📚 Aide NikoForge:")
        print("\n  Commandes:")
        print("    quit/exit/q    - Quitter NikoForge")
        print("    stats          - Afficher les statistiques de la session")
        print("    clear          - Effacer l'écran")
        print("    help           - Afficher cette aide")
        print("\n  Utilisation:")
        print("    Tape simplement ta tâche en langage naturel")
        print("    Exemple: 'Crée un script Python qui analyse des logs'")
        print("\n  Mode direct:")
        print("    python nikoforge.py \"Ta tâche ici\"")
        print("\n  Mode interactif:")
        print("    python nikoforge.py -i")
        print()

    @staticmethod
    def print_error(message: str):
        """Affiche un message d'erreur"""
        print(f"\n❌ Erreur: {message}\n")

    @staticmethod
    def print_success(message: str):
        """Affiche un message de succès"""
        print(f"\n✅ {message}\n")

    @staticmethod
    def print_info(message: str):
        """Affiche un message d'information"""
        print(f"\nℹ️  {message}\n")

    @staticmethod
    def print_warning(message: str):
        """Affiche un avertissement"""
        print(f"\n⚠️  {message}\n")

    @staticmethod
    def print_task(task: str):
        """Affiche la tâche en cours"""
        print(f"\n📋 Tâche: {task}\n")
        print(NikoForgeUI.SEPARATOR)

    @staticmethod
    def print_iteration(iteration: int, max_iterations: int):
        """Affiche le numéro d'itération"""
        print(f"\n--- Itération {iteration}/{max_iterations} ---")

    @staticmethod
    def print_tool_call(tool_name: str):
        """Affiche l'appel d'outil"""
        print(f"\n🔧 Outil: {tool_name}")

    @staticmethod
    def print_model_response():
        """Affiche le message d'attente de la réponse du modèle"""
        print("🤖 En attente de la réponse du modèle...", end="", flush=True)
        print("\n")  # Nouvelle ligne après "En attente..."

    @staticmethod
    def print_completion():
        """Affiche le message de complétion"""
        print("\n✓ Tâche terminée")
        print(NikoForgeUI.SEPARATOR)
        print("✓ Terminé !\n")