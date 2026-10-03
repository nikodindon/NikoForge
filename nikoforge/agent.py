"""Boucle de l'agent : une tâche, des outils, un résultat.

Corrections portées ici (``docs/REFONTE.md``) :

* **C2** — ``iteration`` est **local à la tâche**. En v2, le compteur n'était jamais remis à
  zéro : ``max_iterations`` était un budget de session, et après 20 itérations cumulées
  ``run()`` retournait une chaîne vide sans le moindre message.
* **C3** — deux rendus distincts : ``render_result_for_model`` (champs explicites, pas de
  ``repr()`` Python) pour le modèle, ``tools.format_tool_result`` pour l'humain.
* **C9** — l'approbation a lieu **avant** l'exécution, outil par outil.
* **C16** — la validation passe par le schéma de ``protocol`` : une ``new_content`` vide est
  acceptée, donc supprimer du texte est possible.
* **C6** (volet affichage) — les sorties envoyées au modèle sont bornées, tête et queue.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TextIO

from .config import Config
from .context import ContextManager
from .llm import LLM, LLMError
from .prompt import get_system_prompt
from .protocol import (
    SPECS_BY_NAME,
    ProtocolError,
    ToolArgumentsError,
    ToolCall,
    ToolSpec,
    prepare_call,
)
from .tools import ToolResult, Tools, format_tool_result

#: Au-delà, une sortie d'outil est coupée avant d'être envoyée au modèle (bug C6).
MODEL_OUTPUT_LIMIT = 8000

ALLOW = "allow"
ASK = "ask"
DENY = "deny"

#: Politique par défaut : la lecture est libre, tout ce qui modifie le disque ou exécute une
#: commande demande confirmation (bug C9 : en v2, la question était posée *après* l'exécution).
DEFAULT_RULES: dict[str, str] = {
    "list_files": ALLOW,
    "read_file": ALLOW,
    "write_file": ASK,
    "edit_file": ASK,
    "bash": ASK,
}

SUMMARY_INSTRUCTIONS = (
    "Résume les échanges suivants pour un agent de coding qui doit poursuivre la tâche.\n"
    "Conserve : la demande initiale, les décisions prises, les fichiers créés ou modifiés "
    "et leur contenu utile, les erreurs rencontrées et ce qui a été fait pour les résoudre.\n"
    "N'invente rien. Va droit au but, en français, sous forme de liste."
)


# --------------------------------------------------------------------------- #
# Résultat d'exécution
# --------------------------------------------------------------------------- #


@dataclass
class RunResult:
    """Ce qui s'est réellement passé pendant une tâche."""

    text: str = ""
    iterations: int = 0
    tool_calls: int = 0
    denied: int = 0
    stop_reason: str = "done"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.stop_reason == "done"

    def summary(self) -> str:
        return (
            f"{self.iterations} itération(s), {self.tool_calls} appel(s) d'outil"
            + (f", {self.denied} refusé(s)" if self.denied else "")
            + f" — {self.stop_reason}"
        )


# --------------------------------------------------------------------------- #
# Politique d'approbation
# --------------------------------------------------------------------------- #


@dataclass
class ApprovalPolicy:
    """Qui a le droit de faire quoi, et quand la question se pose.

    ``auto_approve`` correspond à ``--yes`` : l'utilisateur a déjà dit oui à tout. C'est le
    réglage du mode « une seule tâche » (``-p``), où la consigne tapée vaut consentement.
    """

    rules: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_RULES))
    default: str = ASK
    auto_approve: bool = False

    def decide(self, tool_name: str) -> str:
        if self.auto_approve:
            return ALLOW
        return self.rules.get(tool_name, self.default)

    def allow_always(self, tool_name: str) -> None:
        merged = dict(self.rules)
        merged[tool_name] = ALLOW
        self.rules = merged


#: Répond « oui » ou « non » à une demande d'approbation.
Approver = Callable[[ToolCall], bool]


# --------------------------------------------------------------------------- #
# Rendu destiné au modèle
# --------------------------------------------------------------------------- #


def truncate_for_model(text: str, limit: int = MODEL_OUTPUT_LIMIT) -> str:
    """Borne un texte en gardant la tête **et** la queue.

    La queue compte : c'est là que se trouve la trace d'erreur d'un test qui échoue. En v2,
    rien n'était borné, et un ``cat`` sur un gros fichier saturait le contexte en une fois.
    """
    if len(text) <= limit:
        return text
    head = (limit * 2) // 3
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n[… {omitted} caractères omis …]\n{text[-tail:]}"


def render_result_for_model(call: ToolCall, result: ToolResult) -> str:
    """Texte du résultat d'outil **destiné au modèle**.

    La v2 envoyait au modèle la même chaîne que celle affichée à l'humain : une ``repr()``
    Python avec les sauts de ligne échappés, précédée de « ✓ Succès » et du mot « Données »
    (bug C3). Ici chaque information est nommée.
    """
    status = "succès" if result.success else "échec"
    lines = [f"[outil {call.name} — {status}]"]

    if isinstance(result.data, dict) and "exit_code" in result.data:
        lines.append(f"code de sortie : {result.data['exit_code']}")
        stdout = result.data.get("stdout") or ""
        stderr = result.data.get("stderr") or ""
        if stdout.strip():
            lines.append("sortie standard :\n" + truncate_for_model(stdout))
        if stderr.strip():
            lines.append("sortie d'erreur :\n" + truncate_for_model(stderr))
        if not stdout.strip() and not stderr.strip():
            lines.append("(aucune sortie)")
    elif result.success:
        lines.append(truncate_for_model(str(result.data)))
    else:
        lines.append(f"erreur : {result.error}")

    return "\n".join(lines)


def render_refusal(call: ToolCall, reason: str) -> str:
    """Message renvoyé au modèle quand un appel n'a pas été exécuté."""
    return (
        f"[outil {call.name} — NON EXÉCUTÉ]\n"
        f"{reason}\n"
        "Propose une autre approche, ou explique pourquoi cette action est nécessaire."
    )


def openai_tool_call(call: ToolCall) -> dict[str, Any]:
    """Forme ``tool_calls`` de l'API OpenAI, telle qu'elle doit figurer dans l'historique.

    Sans ce champ, le gabarit de chat du serveur ne peut pas relier l'appel à sa réponse :
    le message assistant reste vide et le modèle rappelle l'outil au tour suivant. Constaté
    sur un serveur réel, avant correction (``docs/REFONTE.md`` C18).
    """
    return {
        "id": call.call_id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(dict(call.arguments), ensure_ascii=False),
        },
    }


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #


class Agent:
    """Boucle de l'agent : interroge le modèle, exécute les outils, recommence."""

    def __init__(
        self,
        config: Config,
        *,
        llm: LLM | None = None,
        policy: ApprovalPolicy | None = None,
        approver: Approver | None = None,
        should_stop: Callable[[], bool] | None = None,
        stream: TextIO | None = None,
        echo: bool = True,
    ):
        self.config = config
        self.tools = Tools(base_dir=str(config.workdir))
        self.context = ContextManager(
            max_tokens=config.context.max_tokens,
            compaction_threshold=config.context.compaction_threshold,
            summary_tokens=config.context.summary_tokens,
        )
        self.policy = policy or ApprovalPolicy()
        self.approver = approver
        self.should_stop = should_stop
        self.stream = stream if stream is not None else sys.stdout
        self.echo = echo

        self.max_iterations = config.agent.max_iterations
        self.iteration = 0
        self.llm = llm or LLM(
            config, on_text=self._on_text, on_reasoning=self._on_reasoning
        )

    # -- affichage --------------------------------------------------------- #

    def _on_text(self, piece: str) -> None:
        if self.echo:
            print(piece, end="", flush=True)

    def _on_reasoning(self, piece: str) -> None:
        if self.echo:
            print(piece, end="", flush=True, file=self.stream)

    def _say(self, text: str = "") -> None:
        if self.echo:
            print(text, file=self.stream, flush=True)

    # -- boucle ------------------------------------------------------------ #

    def run(self, user_message: str) -> RunResult:
        """Exécute une tâche de bout en bout."""
        # C2 : le budget d'itérations est celui de CETTE tâche.
        self.iteration = 0
        self.context.add_message("user", user_message)

        result = RunResult()
        final_text = ""

        while self.iteration < self.max_iterations:
            if self.should_stop is not None and self.should_stop():
                result.stop_reason = "cancelled"
                break

            self.iteration += 1
            result.iterations = self.iteration

            if self.context.needs_compaction():
                self._compact()

            system_prompt = get_system_prompt(self.config.workdir)
            try:
                completion = self.llm.complete(self.context.build_messages(system_prompt))
            except LLMError as exc:
                result.stop_reason = "error"
                result.error = str(exc)
                result.text = final_text
                return result

            if completion.usage is not None:
                self.context.record_usage(
                    completion.usage.prompt_tokens, completion.usage.completion_tokens
                )

            if not completion.text.strip() and not completion.calls:
                result.stop_reason = "no_response"
                result.text = final_text
                return result

            if completion.text.strip():
                self._say(completion.text)

            native = [call for call in completion.calls if call.call_id]
            if native:
                # Protocole natif : la forme attendue par un gabarit de chat OpenAI est un
                # message assistant porteur des `tool_calls`, puis des messages `tool`.
                # Sans cela, le modèle voit un tour assistant vide, ne relie pas la réponse
                # à son appel, et rappelle l'outil indéfiniment (bug C18).
                self.context.add_message(
                    "assistant",
                    completion.text,
                    tool_calls=[openai_tool_call(call) for call in native],
                )
            else:
                self.context.add_message("assistant", completion.text)
            final_text = completion.text
            self._say()

            if completion.incomplete:
                self._say(
                    "⚠ réponse coupée par la limite de tokens : le dernier appel d'outil "
                    "est incomplet et n'a pas été exécuté."
                )

            if not completion.calls:
                result.stop_reason = "done"
                break

            for call in completion.calls:
                # Un refus n'interrompt pas la tâche : le modèle reçoit la raison et peut
                # proposer autre chose. Abandonner au premier refus serait brutal.
                text = self._run_call(call, result)
                if call.call_id:
                    self.context.add_message(
                        "tool", text, tool_call_id=call.call_id, name=call.name
                    )
                else:
                    self.context.add_message("user", text)

        else:
            result.stop_reason = "max_iterations"

        result.text = final_text
        return result

    # -- outils ------------------------------------------------------------ #

    def _run_call(self, call: ToolCall, result: RunResult) -> str:
        """Valide, demande l'autorisation, exécute, et retourne le texte pour le modèle."""
        self._say(f"\n🔧 {call.name}")

        try:
            prepared = prepare_call(call, SPECS_BY_NAME)
        except ToolArgumentsError as exc:
            # Une erreur de schéma est renvoyée au modèle : il peut se corriger.
            self._say(f"   ✖ arguments refusés : {exc}")
            return render_refusal(call, f"arguments refusés : {exc}")
        except ProtocolError as exc:
            return render_refusal(call, f"appel illisible : {exc}")

        spec: ToolSpec | None = SPECS_BY_NAME.get(prepared.name)
        decision = self.policy.decide(prepared.name)

        if decision == DENY:
            result.denied += 1
            self._say("   ⊘ refusé par la politique")
            return render_refusal(prepared, "action interdite par la politique d'approbation.")

        if decision == ASK:
            if self.approver is None:
                result.denied += 1
                self._say("   ⊘ aucune confirmation possible")
                return render_refusal(
                    prepared,
                    "cette action demande une confirmation, mais aucune n'est disponible "
                    "dans ce mode d'exécution.",
                )
            if not self.approver(prepared):
                result.denied += 1
                self._say("   ⊘ refusé par l'utilisateur")
                return render_refusal(prepared, "l'utilisateur a refusé cette action.")

        tool_result = self._dispatch(prepared, spec)
        result.tool_calls += 1
        self._say(format_tool_result(tool_result))
        return render_result_for_model(prepared, tool_result)

    def _dispatch(self, call: ToolCall, spec: ToolSpec | None) -> ToolResult:
        """Appelle la méthode de ``Tools`` correspondante."""
        function = getattr(self.tools, call.name, None)
        if function is None:
            return ToolResult(False, None, f"outil non implémenté : {call.name}")
        try:
            return function(**dict(call.arguments))
        except TypeError as exc:
            return ToolResult(False, None, f"paramètres incompatibles : {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, None, f"erreur d'exécution : {exc}")

    # -- compaction -------------------------------------------------------- #

    def _compact(self) -> None:
        self._say("⚠ contexte trop grand, compaction en cours…")

        def summarize(transcript: str) -> str:
            completion = self.llm.complete(
                [
                    {"role": "system", "content": SUMMARY_INSTRUCTIONS},
                    {"role": "user", "content": transcript},
                ],
                max_tokens=self.config.context.summary_tokens,
                use_tools=False,
            )
            return completion.text

        before = len(self.context.messages)
        try:
            compacted = self.context.compact(summarize)
        except LLMError as exc:
            self._say(f"✖ compaction impossible : {exc}")
            return

        if compacted:
            self._say(
                f"✓ contexte compacté : {before} → {len(self.context.messages)} messages"
            )
        else:
            self._say("✖ rien à compacter")

    # -- statistiques ------------------------------------------------------ #

    def get_stats(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "context_stats": self.context.get_stats(),
        }

    def save_context(self, path: str) -> None:
        self.context.save_to_file(path)

    def load_context(self, path: str) -> None:
        self.context.load_from_file(path)
