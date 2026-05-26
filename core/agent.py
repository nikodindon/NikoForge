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
from .ui import NikoForgeUI


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
            # Note: response est déjà affichée en streaming dans _get_model_response

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

            print("🤖 En attente de la réponse du modèle...", end="", flush=True)

            response = self.client.chat.completions.create(
                model=self.config["llm"]["model"],
                messages=messages,
                temperature=self.config["llm"]["temperature"],
                max_tokens=self.config["llm"]["max_tokens"],
                timeout=self.config["llm"]["timeout"],
                stream=True  # 🔥 Streaming activé !
            )

            # Extraire le contenu avec streaming
            full_content = ""
            print("\n")  # Nouvelle ligne après "En attente..."

            for chunk in response:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    # Afficher en temps réel
                    if hasattr(delta, 'content') and delta.content:
                        print(delta.content, end="", flush=True)
                        full_content += delta.content
                    # Certains modèles utilisent reasoning_content
                    elif hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        print(delta.reasoning_content, end="", flush=True)
                        full_content += delta.reasoning_content

            print()  # Nouvelle ligne à la fin
            return full_content
        except Exception as e:
            print(f"✗ Erreur modèle: {str(e)}")
            return None

    def _extract_tool_calls(self, response: str) -> list:
        """Extrait les appels d'outils de la réponse (format XML)"""
        import re

        tool_calls = []

        # Chercher <tool_calls>...</tool_calls>
        # Utilisation de regex pour capturer le contenu entre les balises
        pattern = r'<tool_calls>(.*?)</tool_calls>'
        matches = re.findall(pattern, response, re.DOTALL)

        for match in matches:
            # Extraire chaque outil <tool name="...">...</tool>
            tool_pattern = r'<tool name="([^"]+)">(.*?)</tool>'
            tools = re.findall(tool_pattern, match, re.DOTALL)

            for name, content in tools:
                # Extraire les paramètres <param name="...">...</param>
                params = {}
                param_pattern = r'<param name="([^"]+)">(.*?)</param>'
                params_matches = re.findall(param_pattern, content, re.DOTALL)

                for param_name, param_value in params_matches:
                    params[param_name] = param_value.strip()

                tool_calls.append({
                    "name": name,
                    "params": params
                })

        return tool_calls

    def _parse_tool_params(self, params_str: str) -> Dict[str, str]:
        """Parse les paramètres d'un outil (format clé:valeur ou JSON)"""
        params_str = params_str.strip()

        # Essayer JSON d'abord
        try:
            return json.loads(params_str)
        except json.JSONDecodeError:
            pass

        # Parser format "key: value"
        result = {}
        lines = params_str.split('\n')
        current_key = None
        current_values = []

        for line in lines:
            line = line.rstrip()

            # Si la ligne contient ":" c'est probablement une nouvelle clé
            if ':' in line and not line.strip().startswith(' '):
                # Sauvegarder la clé précédente
                if current_key:
                    result[current_key] = '\n'.join(current_values).strip()

                # Nouvelle clé
                parts = line.split(':', 1)
                current_key = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else ''
                current_values = [value] if value else []
            else:
                # Continuer la valeur actuelle
                current_values.append(line)

        # Sauvegarder la dernière clé
        if current_key:
            result[current_key] = '\n'.join(current_values).strip()

        return result

    def _execute_tool(self, tool_call: Dict[str, Any]) -> ToolResult:
        """Exécute un outil"""
        tool_name = tool_call["name"]
        params = tool_call["params"]  # Maintenant c'est déjà un dict

        try:
            # Router vers le bon outil
            if tool_name == "read_file":
                path = params.get("path") or params.get("raw")
                if not path:
                    return ToolResult(False, None, "Paramètre 'path' manquant")
                return self.tools.read_file(path)

            elif tool_name == "write_file":
                path = params.get("path")
                content = params.get("content") or params.get("raw") or ""
                if not path:
                    return ToolResult(False, None, "Paramètre 'path' manquant")
                return self.tools.write_file(path, content)

            elif tool_name == "edit_file":
                path = params.get("path")
                old_content = params.get("old_content")
                new_content = params.get("new_content")
                if not all([path, old_content, new_content]):
                    return ToolResult(False, None, "Paramètres manquants pour edit_file")
                return self.tools.edit_file(path, old_content, new_content)

            elif tool_name == "bash":
                command = params.get("command") or params.get("raw")
                timeout = params.get("timeout") or self.config["agent"]["tool_timeout"]
                # Convertir timeout en int si c'est une string
                if isinstance(timeout, str):
                    try:
                        timeout = int(timeout)
                    except ValueError:
                        timeout = self.config["agent"]["tool_timeout"]
                if not command:
                    return ToolResult(False, None, "Paramètre 'command' manquant")
                return self.tools.bash(command, timeout)

            elif tool_name == "list_files":
                path = params.get("path", ".")
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