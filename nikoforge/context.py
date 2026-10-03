"""
Gestion du contexte et de la compaction
"""

import json
from typing import List, Dict, Any
from datetime import datetime


class ContextManager:
    """Gère le contexte de conversation avec compaction intelligente"""

    def __init__(self, max_tokens: int = 32000, compaction_threshold: float = 0.8):
        self.max_tokens = max_tokens
        self.compaction_threshold = compaction_threshold
        self.messages: List[Dict[str, str]] = []
        self.summary: str = ""
        self.compaction_count = 0

    def add_message(self, role: str, content: str):
        """Ajoute un message à l'historique"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def get_messages(self) -> List[Dict[str, str]]:
        """Retourne les messages avec résumé si compaction"""
        if self.compaction_count > 0:
            # Insérer le résumé au début
            result = [{
                "role": "system",
                "content": f"Résumé des échanges précédents:\n{self.summary}"
            }]
            result.extend(self.messages)
            return result
        return self.messages

    def estimate_tokens(self, text: str) -> int:
        """Estime le nombre de tokens (approximation: 1 token ≈ 4 caractères)"""
        return len(text) // 4

    def estimate_context_size(self) -> int:
        """Estime la taille totale du contexte en tokens"""
        total = 0
        for msg in self.messages:
            total += self.estimate_tokens(msg["content"])
        if self.summary:
            total += self.estimate_tokens(self.summary)
        return total

    def needs_compaction(self) -> bool:
        """Vérifie si le contexte doit être compacté"""
        current_size = self.estimate_context_size()
        threshold = self.max_tokens * self.compaction_threshold
        return current_size >= threshold

    def compact(self, summary_tokens: int = 1000):
        """Compacte le contexte en générant un résumé"""
        if len(self.messages) < 4:
            return  # Pas assez de messages pour compacter

        # Garder les 2 derniers messages (user + assistant)
        recent_messages = self.messages[-2:]
        old_messages = self.messages[:-2]

        # Générer un résumé simple
        self.summary = self._generate_summary(old_messages, summary_tokens)
        self.messages = recent_messages
        self.compaction_count += 1

    def _generate_summary(self, messages: List[Dict[str, str]], max_tokens: int) -> str:
        """Génère un résumé des messages"""
        summary_parts = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            # Tronquer si trop long
            if self.estimate_tokens(content) > max_tokens // len(messages):
                content = content[:max_tokens * 4 // len(messages)] + "..."

            summary_parts.append(f"[{role}]: {content}")

        summary = "\n\n".join(summary_parts)

        # Tronquer le résumé final si nécessaire
        while self.estimate_tokens(summary) > max_tokens:
            summary = summary[:len(summary) - 100] + "..."

        return summary

    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur le contexte"""
        return {
            "total_messages": len(self.messages),
            "compaction_count": self.compaction_count,
            "estimated_tokens": self.estimate_context_size(),
            "max_tokens": self.max_tokens,
            "has_summary": bool(self.summary)
        }

    def reset(self):
        """Réinitialise le contexte"""
        self.messages = []
        self.summary = ""
        self.compaction_count = 0

    def save_to_file(self, path: str):
        """Sauvegarde le contexte dans un fichier"""
        data = {
            "messages": self.messages,
            "summary": self.summary,
            "compaction_count": self.compaction_count,
            "stats": self.get_stats()
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_file(self, path: str):
        """Charge le contexte depuis un fichier"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.messages = data.get("messages", [])
        self.summary = data.get("summary", "")
        self.compaction_count = data.get("compaction_count", 0)