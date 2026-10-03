"""Historique de conversation, budget de contexte et compaction.

Trois corrections par rapport à la v2 (``docs/REFONTE.md``) :

* **C7** — la compaction est un **appel au modèle**, pas une concaténation tronquée par
  découpage de chaîne. Et la tâche initiale est épinglée : en v2, ``compact()`` ne gardait que
  les deux derniers messages, si bien que l'agent oubliait ce qu'on lui avait demandé.
* **C7b** — la taille du contexte vient de l'``usage`` **réel** renvoyé par le serveur. En v2
  c'était ``len(texte) // 4``, faux d'environ 25 % sur du code et d'un facteur 4 hors alphabet
  latin : une session en chinois croyait avoir quatre fois plus de place qu'elle n'en avait.
* **C8** — le résumé est replié dans le message ``system`` initial, au lieu d'être ajouté
  comme second message ``system`` au milieu de l'historique.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping

#: Nombre de caractères par token utilisé par l'estimation de repli. Constante nommée pour
#: que sa grossièreté soit visible partout où elle sert.
CHARS_PER_TOKEN = 4

Summarizer = Callable[[str], str]


class ContextManager:
    """Gère l'historique, la mesure du contexte et la compaction.

    ``pinned`` messages de tête (la tâche initiale) ne sont **jamais** compactés, et
    ``keep_recent`` messages récents sont toujours conservés tels quels.
    """

    def __init__(
        self,
        max_tokens: int = 32768,
        compaction_threshold: float = 0.8,
        summary_tokens: int = 1000,
        pinned: int = 1,
        keep_recent: int = 6,
    ):
        self.max_tokens = max_tokens
        self.compaction_threshold = compaction_threshold
        self.summary_tokens = summary_tokens
        self.pinned = pinned
        self.keep_recent = keep_recent

        self.messages: List[Dict[str, Any]] = []
        self.summary: str = ""
        self.compaction_count = 0

        #: ``prompt_tokens`` de la dernière requête, tel que mesuré par le serveur.
        self.last_prompt_tokens: int | None = None
        self.last_completion_tokens: int = 0
        #: Index dans ``messages`` au moment de la mesure : ce qui suit est ajouté à l'estime.
        self._measured_at: int = 0

    # ------------------------------------------------------------------ #
    # Historique
    # ------------------------------------------------------------------ #

    def add_message(self, role: str, content: str, **extra: Any) -> Dict[str, Any]:
        """Ajoute un message et le retourne.

        ``extra`` porte les champs du protocole OpenAI : ``tool_calls`` pour un message
        assistant qui appelle des outils, ``tool_call_id`` et ``name`` pour un message
        ``tool`` qui en renvoie le résultat. Sans ces champs, le gabarit de chat du serveur
        ne peut pas relier un appel à sa réponse — le modèle voit des tours vides et
        rappelle l'outil indéfiniment (constaté en usage réel, voir ``docs/REFONTE.md`` C18).
        """
        message: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        message.update(extra)
        self.messages.append(message)
        return message

    def get_messages(self) -> List[Dict[str, Any]]:
        """L'historique brut, sans le résumé.

        Le résumé ne s'insère plus ici (il était un second message ``system`` au milieu de
        l'historique, bug C8) : voir ``build_messages``.
        """
        return self.messages

    def build_messages(self, system_prompt: str) -> List[Dict[str, Any]]:
        """Messages envoyés au modèle : le system prompt (résumé inclus) puis l'historique.

        Seul ``timestamp`` est retiré : les champs du protocole (``tool_calls``,
        ``tool_call_id``) doivent traverser tels quels, sinon le serveur ne peut pas
        reconstituer les appels d'outils.
        """
        system = system_prompt
        if self.summary:
            system = (
                f"{system_prompt}\n\n"
                "## Résumé des échanges précédents (compactés)\n"
                f"{self.summary}"
            )

        built: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for message in self.messages:
            payload = {key: value for key, value in message.items() if key != "timestamp"}
            payload.setdefault("content", "")
            built.append(payload)
        return built

    def reset(self) -> None:
        self.messages = []
        self.summary = ""
        self.compaction_count = 0
        self.last_prompt_tokens = None
        self.last_completion_tokens = 0
        self._measured_at = 0

    # ------------------------------------------------------------------ #
    # Mesure
    # ------------------------------------------------------------------ #

    def estimate_tokens(self, text: str) -> int:
        """Estimation grossière, **utile uniquement en l'absence de mesure du serveur**.

        ``len // 4`` suppose quatre caractères par token : à peu près juste pour de la prose
        latine, faux d'environ 25 % pour du code, et faux d'un facteur 4 pour du chinois. Ce
        n'est utilisé que pour évaluer ce qui a été ajouté depuis la dernière mesure réelle.
        """
        return len(text) // CHARS_PER_TOKEN

    def estimate_context_size(self) -> int:
        """Estimation de l'historique complet, résumé compris."""
        total = sum(self.estimate_tokens(message["content"]) for message in self.messages)
        if self.summary:
            total += self.estimate_tokens(self.summary)
        return total

    def record_usage(self, prompt_tokens: int, completion_tokens: int = 0) -> None:
        """Enregistre la mesure du serveur pour la requête qui vient d'être envoyée."""
        self.last_prompt_tokens = prompt_tokens
        self.last_completion_tokens = completion_tokens
        self._measured_at = len(self.messages)

    def context_size(self) -> int:
        """Taille du contexte : la mesure du serveur, complétée par ce qui a suivi.

        C'est la valeur à utiliser partout. L'estimation seule n'est qu'un repli pour la
        toute première requête, quand aucune mesure n'existe encore.
        """
        if self.last_prompt_tokens is None:
            return self.estimate_context_size()
        added = sum(
            self.estimate_tokens(message["content"])
            for message in self.messages[self._measured_at :]
        )
        return self.last_prompt_tokens + added

    def needs_compaction(self) -> bool:
        return self.context_size() >= self.max_tokens * self.compaction_threshold

    # ------------------------------------------------------------------ #
    # Compaction
    # ------------------------------------------------------------------ #

    def compactable(self) -> int:
        """Nombre de messages réellement compactables (hors tête épinglée et queue gardée)."""
        return max(0, len(self.messages) - self.pinned - self.keep_recent)

    def compact(self, summarize: Summarizer | None = None) -> bool:
        """Compacte les messages du milieu en un résumé, en gardant la tête et la queue.

        ``summarize`` reçoit le texte des messages à compacter et retourne un résumé. Il est
        fourni par l'appelant (l'agent, qui possède l'accès au modèle) : ce module n'a ainsi
        aucune dépendance réseau et reste testable avec une simple fonction.

        Retourne ``True`` si quelque chose a été compacté.

        En cas d'échec du résumé, **rien n'est supprimé** : mieux vaut un contexte trop grand
        qu'un historique amputé sans résumé.
        """
        if self.compactable() == 0:
            return False

        start = len(self.messages) - self.keep_recent
        # Ne jamais couper entre un message assistant porteur d'appels d'outils et les
        # messages `tool` qui lui répondent : un `tool` orphelin fait échouer le gabarit de
        # chat du serveur (« message tool sans tool_call correspondant »).
        while start > self.pinned and self.messages[start]["role"] == "tool":
            start -= 1

        old = self.messages[self.pinned : start]
        recent = self.messages[start:]
        if not old:
            return False

        transcript = self._transcript(old)
        text = summarize(transcript) if summarize else self._fallback_summary(transcript)

        if not text or not text.strip():
            return False

        self.summary = text.strip()
        self.messages = self.messages[: self.pinned] + recent
        self.compaction_count += 1
        # La mesure du serveur ne vaut plus rien : l'historique a changé de taille.
        self.last_prompt_tokens = None
        self._measured_at = 0
        return True

    def _transcript(self, messages: Iterable[Mapping[str, Any]]) -> str:
        return "\n\n".join(
            f"[{message['role']}] : {message['content']}" for message in messages
        )

    def _fallback_summary(self, transcript: str) -> str:
        """Repli quand aucun résumé par le modèle n'est disponible.

        Volontairement différent de la v2 : on ne découpe pas la chaîne en plein milieu d'un
        mot, on coupe sur une frontière de ligne et on le dit.
        """
        limit = self.summary_tokens * CHARS_PER_TOKEN
        if len(transcript) <= limit:
            return transcript
        return transcript[:limit].rsplit("\n", 1)[0] + "\n[…] (tronqué faute de résumé disponible)"

    # ------------------------------------------------------------------ #
    # Persistance et statistiques
    # ------------------------------------------------------------------ #

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_messages": len(self.messages),
            "compaction_count": self.compaction_count,
            "estimated_tokens": self.context_size(),
            "max_tokens": self.max_tokens,
            "has_summary": bool(self.summary),
        }

    def save_to_file(self, path: str) -> None:
        data = {
            "messages": self.messages,
            "summary": self.summary,
            "compaction_count": self.compaction_count,
            "stats": self.get_stats(),
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def load_from_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        self.messages = data.get("messages", [])
        self.summary = data.get("summary", "")
        self.compaction_count = data.get("compaction_count", 0)
        self.last_prompt_tokens = None
        self._measured_at = 0
