"""
Outils de base pour NikoForge
"""

import os
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any


class ToolResult:
    """Résultat d'un outil"""
    def __init__(self, success: bool, data: Any, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }


class Tools:
    """Collection d'outils pour l'agent"""

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir).resolve()

    def read_file(self, path: str) -> ToolResult:
        """Lit le contenu d'un fichier"""
        try:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                return ToolResult(False, None, f"Fichier non trouvé: {path}")

            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return ToolResult(True, content)
        except Exception as e:
            return ToolResult(False, None, f"Erreur lecture: {str(e)}")

    def write_file(self, path: str, content: str) -> ToolResult:
        """Écrit ou remplace un fichier"""
        try:
            full_path = self._resolve_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return ToolResult(True, f"Fichier écrit: {path}")
        except Exception as e:
            return ToolResult(False, None, f"Erreur écriture: {str(e)}")

    def edit_file(self, path: str, old_content: str, new_content: str) -> ToolResult:
        """Modifie une partie d'un fichier"""
        try:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                return ToolResult(False, None, f"Fichier non trouvé: {path}")

            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()

            if old_content not in current_content:
                return ToolResult(False, None, f"Ancien contenu non trouvé dans {path}")

            updated_content = current_content.replace(old_content, new_content)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)

            return ToolResult(True, f"Fichier modifié: {path}")
        except Exception as e:
            return ToolResult(False, None, f"Erreur modification: {str(e)}")

    def bash(self, command: str, timeout: int = 30) -> ToolResult:
        """Exécute une commande shell"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.base_dir
            )

            output = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }

            success = result.returncode == 0
            error = result.stderr if result.returncode != 0 else None

            return ToolResult(success, output, error)
        except subprocess.TimeoutExpired:
            return ToolResult(False, None, f"Commande timeout après {timeout}s")
        except Exception as e:
            return ToolResult(False, None, f"Erreur exécution: {str(e)}")

    def list_files(self, path: str = ".") -> ToolResult:
        """Liste les fichiers d'un répertoire"""
        try:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                return ToolResult(False, None, f"Répertoire non trouvé: {path}")

            if not full_path.is_dir():
                return ToolResult(False, None, f"Ce n'est pas un répertoire: {path}")

            files = []
            for item in full_path.iterdir():
                files.append({
                    "name": item.name,
                    "path": str(item.relative_to(self.base_dir)),
                    "type": "dir" if item.is_dir() else "file"
                })

            return ToolResult(True, files)
        except Exception as e:
            return ToolResult(False, None, f"Erreur listing: {str(e)}")

    def _resolve_path(self, path: str) -> Path:
        """Résout un chemin relatif ou absolu"""
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        return (self.base_dir / path_obj).resolve()


def format_tool_result(result: ToolResult) -> str:
    """Formate le résultat d'un outil pour l'affichage"""
    if result.success:
        output = f"✓ Succès\n"
        if result.data:
            output += f"Données: {result.data}\n"
        return output
    else:
        return f"✗ Erreur: {result.error}"