"""
Boucle principale de l'agent NikoForge
"""

import json
import time
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from .tools import Tools, ToolResult, format_tool_result
from .context import ContextManager
from .prompt import get_system_prompt


class Agent:
    """Agent de coding principal"""

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.tools = Tools(base_dir=".")
        self.context = ContextManager(
            max_tokens=self.config["context"]["max_tokens"],
            compaction_threshold=self.config["context"]["compaction_threshold"]
        )
        self.client = self._init_client()
        self.iteration = 0
        self.max_iterations = self.config["agent"]["max_iterations"]

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Charge la configuration"""
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration non trouvée: {config_path}")

        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _init_client(self):
        """Initialise le client OpenAI"""
        if OpenAI is None:
            raise ImportError("openai package non installé. Installez-le avec: pip install openai")

        return OpenAI(
            base_url=self.config["llm"]["base_url"],
            api_key=self.config["llm"]["api_key"]
        )

    def run(self, user_message: str, interactive: bool = False) -> str:
        """Exécute l'agent avec un message utilisateur"""
        # Ajouter le message utilisateur au contexte
        self.context.add_message("user", user_message)

        final_response = ""

        # Boucle principale
        while self.iteration < self.max_iterations:
            self.iteration += 1
            print(f"\n--- Itération {self.iteration}/{self.max_iterations} ---")

            # Vérifier si on doit compacter le contexte
            if self.context.needs_compaction():
                print("⚠️  Contexte trop grand, compaction en cours...")
                self.context.compact(summary_tokens=self.config["context"]["summary_tokens"])
                print(f"✓ Contexte compacté (résumé: {len(self.context.summary)} chars)")

            # Obtenir la réponse du modèle
            response = self._get_model_response()

            if not response:
                print("✗ Pas de réponse du modèle")
                break

            final_response = response

            # Ajouter la réponse au contexte
            self.context.add_message("assistant", response)
            print(f"\n🤖 Agent:\n{response}")

            # Extraire et exécuter les outils
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # Pas d'outils appelés, on a fini
                print("\n✓ Tâche terminée")
                break

            # Exécuter les outils
            for tool_call in tool_calls:
                tool_result = self._execute_tool(tool_call)
                print(f"\n🔧 Outil: {tool_call['name']}")
                print(format_tool_result(tool_result))

                # Ajouter le résultat au contexte
                result_message = f"[outil: {tool_call['name']}]\n{format_tool_result(tool_result)}"
                self.context.add_message("user", result_message)

            # En mode interactif, demander confirmation
            if interactive:
                user_input = input("\nContinuer? (o/n/q): ").strip().lower()
                if user_input == 'n':
                    print("Arrêt demandé par l'utilisateur")
                    break
                elif user_input == 'q':
                    print("Sortie")
                    return final_response

        return final_response

    def _get_model_response(self) -> Optional[str]:
        """Obtient une réponse du modèle"""
        try:
            messages = [
                {"role": "system", "content": get_system_prompt()}
            ]
            messages.extend(self.context.get_messages())

            response = self.client.chat.completions.create(
                model=self.config["llm"]["model"],
                messages=messages,
                temperature=self.config["llm"]["temperature"],
                max_tokens=self.config["llm"]["max_tokens"],
                timeout=self.config["llm"]["timeout"]
            )

            # Extraire le contenu (gérer reasoning_content si présent)
            message = response.choices[0].message
            content = message.content

            # Certains modèles renvoient reasoning_content au lieu de content
            if not content and hasattr(message, 'reasoning_content'):
                content = message.reasoning_content

            return content
        except Exception as e:
            print(f"✗ Erreur modèle: {str(e)}")
            return None

    def _extract_tool_calls(self, response: str) -> list:
        """Extrait les appels d'outils de la réponse"""
        tool_calls = []

        # Format attendu: [outil: nom_outil]
        # suivi de paramètres en JSON ou texte
        lines = response.split('\n')
        current_tool = None
        params = []

        for line in lines:
            line = line.strip()

            # Détection d'appel d'outil
            if line.startswith('[outil:') and line.endswith(']'):
                # Sauvegarder l'outil précédent s'il y en a un
                if current_tool:
                    tool_calls.append({
                        "name": current_tool,
                        "params": "\n".join(params).strip()
                    })

                # Nouvel outil
                current_tool = line[7:-1].strip()
                params = []

            elif current_tool:
                params.append(line)

        # Sauvegarder le dernier outil
        if current_tool:
            tool_calls.append({
                "name": current_tool,
                "params": "\n".join(params).strip()
            })

        return tool_calls

    def _execute_tool(self, tool_call: Dict[str, str]) -> ToolResult:
        """Exécute un outil"""
        tool_name = tool_call["name"]
        params = tool_call["params"]

        try:
            # Parser les paramètres (JSON ou texte)
            try:
                args = json.loads(params)
            except json.JSONDecodeError:
                args = {"raw": params}

            # Router vers le bon outil
            if tool_name == "read_file":
                path = args.get("path") or args.get("raw")
                return self.tools.read_file(path)

            elif tool_name == "write_file":
                path = args.get("path")
                content = args.get("content") or args.get("raw")
                return self.tools.write_file(path, content)

            elif tool_name == "edit_file":
                path = args.get("path")
                old_content = args.get("old_content")
                new_content = args.get("new_content")
                return self.tools.edit_file(path, old_content, new_content)

            elif tool_name == "bash":
                command = args.get("command") or args.get("raw")
                timeout = args.get("timeout", self.config["agent"]["tool_timeout"])
                return self.tools.bash(command, timeout)

            elif tool_name == "list_files":
                path = args.get("path", ".")
                return self.tools.list_files(path)

            else:
                return ToolResult(False, None, f"Outil inconnu: {tool_name}")

        except Exception as e:
            return ToolResult(False, None, f"Erreur exécution outil: {str(e)}")

    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur l'exécution"""
        return {
            "iteration": self.iteration,
            "context_stats": self.context.get_stats()
        }

    def save_context(self, path: str):
        """Sauvegarde le contexte"""
        self.context.save_to_file(path)

    def load_context(self, path: str):
        """Charge le contexte"""
        self.context.load_from_file(path)