"""Accès au serveur d'inférence : streaming, outils, raisonnement, erreurs.

Ce module isole tout ce qui touche au réseau et au SDK ``openai``. L'agent ne connaît que
``Completion`` et des exceptions nommées — ce qui permet de tester la boucle sans serveur et
de produire des messages d'erreur actionnables.

Corrections portées ici (``docs/REFONTE.md``) :

* **C4** — ``reasoning_content`` est conservé **à part** et n'est jamais renvoyé au modèle.
  En v2, la réflexion du modèle était concaténée au contenu final et donc stockée dans
  l'historique, puis relue à chaque tour.
* **C10** — délai d'attente par défaut non nul, reprise avec attente croissante sur les
  erreurs transitoires, et distinction explicite entre « serveur injoignable », « modèle
  inconnu », « contexte trop long » et « outils non supportés ».
* Les **tokens réels** (``usage``) sont remontés, au lieu de l'estimation ``len // 4``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .config import Config
from .protocol import (
    ToolCall,
    openai_tools,
    parse_response,
)
from .server import pick_model, probe

DEFAULT_BACKOFF = 1.0


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #


class LLMError(Exception):
    """Erreur d'accès au modèle, avec un message destiné à l'utilisateur."""

    retryable = False


class ServerUnreachable(LLMError):
    """Le serveur ne répond pas. La cause la plus fréquente : il n'est pas lancé."""

    retryable = True


class ModelNotFound(LLMError):
    """Le serveur répond mais ne connaît pas ce modèle."""


class ToolsUnsupported(LLMError):
    """Le serveur (ou son gabarit de chat) refuse le champ ``tools``."""


class ContextTooLong(LLMError):
    """La requête dépasse la fenêtre de contexte du serveur."""


class RequestTimedOut(LLMError):
    retryable = True


class StreamInterrupted(LLMError):
    """Le flux s'est interrompu en cours de génération."""

    retryable = True


class ServerError(LLMError):
    """Le serveur a renvoyé une erreur 5xx : transitoire par nature, donc réessayable."""

    retryable = True


# --------------------------------------------------------------------------- #
# Valeurs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Capabilities:
    """Ce que le serveur sait faire. Mesuré, pas deviné.

    ``GET /v1/models`` n'est pas fiable pour cela : le serveur de référence de ce projet
    annonce ``capabilities: ["completion"]`` tout en acceptant parfaitement ``tools``. La
    bonne source est ``GET /props`` → ``chat_template_caps`` (mesuré le 2026-10-03).
    """

    supports_tools: bool = False
    supports_system_role: bool = True
    supports_parallel_tool_calls: bool = False
    n_ctx: int | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class Completion:
    """Une réponse de modèle, déjà décodée."""

    text: str = ""
    reasoning: str = ""
    calls: tuple[ToolCall, ...] = ()
    #: La réponse a été coupée : un bloc d'appel est resté ouvert.
    incomplete: bool = False
    usage: Usage | None = None
    finish_reason: str | None = None
    model: str = ""
    elapsed: float = 0.0
    #: Nombre de tentatives avant d'obtenir cette réponse (1 = du premier coup).
    attempts: int = 1


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class LLM:
    """Client du serveur, avec reprise sur erreur et repli de protocole.

    ``on_text`` et ``on_reasoning`` sont appelés au fil du flux : c'est ce qui permet
    l'affichage en temps réel sans que le client connaisse l'interface.
    """

    def __init__(
        self,
        config: Config,
        *,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        max_retries: int = 2,
        backoff: float = DEFAULT_BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.on_text = on_text
        self.on_reasoning = on_reasoning
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep  # injectable : les tests ne doivent pas attendre pour de vrai

        self._capabilities: Capabilities | None = None
        self._model: str | None = config.llm.model or None
        self._tools_enabled: bool | None = None

    # -- découverte ------------------------------------------------------- #

    @property
    def model(self) -> str:
        """Nom du modèle, découvert auprès du serveur si la configuration le laisse vide."""
        if self._model:
            return self._model

        result = probe(self.config.llm.base_url)
        if not result.ok:
            raise ServerUnreachable(
                f"serveur injoignable ({self.config.llm.base_url}) : {result.error}. "
                f"{result.detail}"
            )

        model, _ = pick_model(result)
        if model is None:
            raise ModelNotFound(
                "le serveur répond mais n'annonce aucun modèle sur /v1/models. "
                "Chargez un modèle, ou précisez --model."
            )
        self._model = model
        return model

    def capabilities(self, refresh: bool = False) -> Capabilities:
        """Interroge ``/props``. Résultat mis en cache : un seul aller-retour par session."""
        if self._capabilities is not None and not refresh:
            return self._capabilities
        self._capabilities = discover_capabilities(
            self.config.llm.base_url, timeout=min(self.config.llm.timeout or 10.0, 10.0)
        )
        return self._capabilities

    @property
    def uses_tools(self) -> bool:
        """Le protocole natif est-il utilisé ? Ten compte du mode forcé et des capacités."""
        if self._tools_enabled is not None:
            return self._tools_enabled
        if self.config.llm.protocol == "text":
            self._tools_enabled = False
        elif self.config.llm.protocol == "native":
            self._tools_enabled = True
        else:  # "auto"
            self._tools_enabled = self.capabilities().supports_tools
        return self._tools_enabled

    # -- requête ----------------------------------------------------------- #

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        max_tokens: int | None = None,
        use_tools: bool | None = None,
    ) -> Completion:
        """Envoie une requête et renvoie la réponse décodée.

        ``use_tools=False`` désactive les outils pour cet appel : c'est ce qu'utilise la
        compaction, où l'on veut un résumé et non un plan d'action.

        Retente sur les erreurs transitoires ; bascule automatiquement du protocole natif au
        protocole textuel si le serveur refuse ``tools``.
        """
        attempt = 0
        tools_wanted = self.uses_tools if use_tools is None else use_tools
        use_tools = tools_wanted
        last_error: LLMError | None = None

        while attempt <= self.max_retries:
            attempt += 1
            try:
                completion = self._request(
                    messages, use_tools=use_tools, max_tokens=max_tokens, attempt=attempt
                )
                return completion
            except ToolsUnsupported:
                # Un protocole forcé ne se replie pas : c'est l'intention explicite de
                # l'utilisateur, une surprise serait pire qu'une erreur claire.
                if use_tools is False or self.config.llm.protocol == "native":
                    raise
                # Le serveur refuse `tools` : on mémorise et on repart en mode textuel.
                self._tools_enabled = False
                use_tools = False
                attempt -= 1  # ce n'est pas la faute du réseau, on ne consomme pas d'essai
                continue
            except LLMError as exc:
                last_error = exc
                if not exc.retryable or attempt > self.max_retries:
                    raise
                self._sleep(self.backoff * (2 ** (attempt - 1)))

        assert last_error is not None
        raise last_error

    def _request(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        use_tools: bool,
        max_tokens: int | None,
        attempt: int,
    ) -> Completion:
        client = self._client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.config.llm.temperature,
            "max_tokens": max_tokens or self.config.llm.max_tokens,
            "stream": True,
            # Sans cette option, le serveur n'envoie pas l'usage dans le flux et l'agent
            # retombe sur une estimation. Les serveurs qui l'ignorent restent acceptés.
            "stream_options": {"include_usage": True},
        }
        if self.config.llm.stop:
            kwargs["stop"] = list(self.config.llm.stop)
        if not self.config.llm.enable_thinking:
            # `chat_template_kwargs` est un champ non standard, passé tel quel à llama-server.
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        if use_tools:
            kwargs["tools"] = openai_tools()
            kwargs["tool_choice"] = "auto"

        started = time.monotonic()
        try:
            stream = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - traduit plus bas
            raise translate_error(exc, self.config, self._model) from exc

        text, reasoning, usage, finish_reason, raw_calls = self._consume(stream)

        parsed = parse_response(text, raw_calls, reasoning)
        return Completion(
            text=parsed.text,
            reasoning=parsed.reasoning,
            calls=parsed.calls,
            incomplete=parsed.incomplete,
            usage=usage,
            finish_reason=finish_reason,
            model=self._model or "",
            elapsed=time.monotonic() - started,
            attempts=attempt,
        )

    def _consume(
        self, stream: Iterable[Any]
    ) -> tuple[str, str, Usage | None, str | None, list[dict[str, Any]]]:
        """Parcourt le flux SSE : texte, raisonnement, fragments d'appels, usage."""
        parts: list[str] = []
        thoughts: list[str] = []
        fragments: dict[int, dict[str, Any]] = {}
        usage: Usage | None = None
        finish_reason: str | None = None

        try:
            for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = Usage(
                        prompt_tokens=getattr(chunk_usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(chunk_usage, "completion_tokens", 0) or 0,
                        total_tokens=getattr(chunk_usage, "total_tokens", 0) or 0,
                    )

                for choice in getattr(chunk, "choices", None) or []:
                    if getattr(choice, "finish_reason", None):
                        finish_reason = choice.finish_reason
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    text_piece = _field(delta, "content")
                    if text_piece:
                        parts.append(text_piece)
                        if self.on_text:
                            self.on_text(text_piece)

                    thought_piece = _field(delta, "reasoning_content")
                    if thought_piece:
                        thoughts.append(thought_piece)
                        if self.on_reasoning:
                            self.on_reasoning(thought_piece)

                    _accumulate_tool_fragments(fragments, getattr(delta, "tool_calls", None))
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise translate_error(exc, self.config, self._model) from exc

        # Les appels natifs arrivent fragmentés : on les recompose dans l'ordre des index
        # avant de les décoder. C'est le seul endroit où `parse_native_calls` peut recevoir
        # des arguments incomplets si on se trompe de reconstitution.
        raw_calls = [
            {"id": slot.get("id"), "function": {"name": slot.get("name"), "arguments": slot.get("arguments")}}
            for _, slot in sorted(fragments.items())
            if slot.get("name")
        ]
        return "".join(parts), "".join(thoughts), usage, finish_reason, raw_calls

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "le paquet `openai` est requis. Installez-le : pip install openai"
            ) from exc

        return OpenAI(
            base_url=self.config.llm.base_url,
            api_key=self.config.llm.api_key,
            # 0 = pas de limite : le SDK distingue 0.0 (« attendre 0 s ») de None.
            timeout=self.config.llm.timeout or None,
            # Le SDK retente lui-même les 5xx et les erreurs de connexion. On le désactive :
            # deux politiques de reprise empilées rendent le nombre de tentatives imprévisible
            # et les délais incontrôlables. Une seule couche, celle d'ici, visible et testée.
            max_retries=0,
        )


# --------------------------------------------------------------------------- #
# Détail du flux
# --------------------------------------------------------------------------- #


def _field(obj: Any, name: str) -> str | None:
    """Lit un champ, y compris dans ``model_extra`` (champs non standard du SDK).

    Nécessaire pour ``reasoning_content``, que llama-server envoie mais que le SDK ne déclare
    pas : suivant la version, il apparaît en attribut ou dans ``model_extra``.
    """
    value = getattr(obj, name, None)
    if value:
        return value
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, Mapping):
        candidate = extra.get(name)
        if candidate:
            return candidate
    return None


def _accumulate_tool_fragments(
    fragments: dict[int, dict[str, Any]], delta_calls: Any
) -> None:
    """Recompose les ``tool_calls`` que le serveur envoie morceau par morceau."""
    if not delta_calls:
        return
    for position, raw in enumerate(delta_calls):
        index = getattr(raw, "index", None)
        if index is None:
            index = position
        slot = fragments.setdefault(index, {"id": None, "name": "", "arguments": ""})

        call_id = getattr(raw, "id", None)
        if call_id:
            slot["id"] = call_id

        function = getattr(raw, "function", None)
        name = getattr(function, "name", None) if function else None
        if name:
            slot["name"] = name
        arguments = getattr(function, "arguments", None) if function else None
        if arguments:
            slot["arguments"] += arguments


def discover_capabilities(base_url: str, timeout: float = 5.0) -> Capabilities:
    """Lit ``/props`` → ``chat_template_caps``. Best effort : jamais d'exception."""
    import json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/").removesuffix("/v1") + "/props"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - les capacités sont une optimisation, pas un prérequis
        return Capabilities()

    if not isinstance(payload, Mapping):
        return Capabilities()

    caps = payload.get("chat_template_caps")
    caps = caps if isinstance(caps, Mapping) else {}
    settings = payload.get("default_generation_settings")
    n_ctx = payload.get("n_ctx")
    if n_ctx is None and isinstance(settings, Mapping):
        n_ctx = settings.get("n_ctx")

    return Capabilities(
        supports_tools=bool(caps.get("supports_tools", False)),
        supports_system_role=bool(caps.get("supports_system_role", True)),
        supports_parallel_tool_calls=bool(caps.get("supports_parallel_tool_calls", False)),
        n_ctx=n_ctx if isinstance(n_ctx, int) and n_ctx > 0 else None,
    )


def translate_error(exc: BaseException, config: Config, model: str | None) -> LLMError:
    """Traduit une exception du SDK (ou du réseau) en erreur nommée et lisible.

    La v2 attrapait tout avec un ``except Exception`` et affichait « ✗ Erreur modèle: … »,
    sans jamais dire que le serveur était éteint ni comment le lancer (bug B2).
    """
    message = str(exc)
    lowered = message.lower()
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )

    if "tools" in lowered or "tool_choice" in lowered:
        if status == 400 or "not supported" in lowered or "unsupported" in lowered:
            return ToolsUnsupported(
                f"le serveur refuse le champ `tools` : {message[:200]}. "
                "Le protocole textuel sera utilisé (config : llm.protocol = \"text\")."
            )

    if isinstance(exc, (ConnectionError, OSError)) or "connect" in lowered:
        return ServerUnreachable(
            f"serveur injoignable ({config.llm.base_url}) : {message[:200]}. "
            "Vérifiez qu'il est lancé (`nikoforge doctor`)."
        )
    if "timeout" in lowered or "timed out" in lowered:
        return RequestTimedOut(
            f"le serveur n'a pas répondu dans le délai imparti "
            f"({config.llm.timeout:g} s). Augmentez llm.timeout si le modèle est lent."
        )
    if status == 404 or "model" in lowered and "not found" in lowered:
        return ModelNotFound(
            f"le serveur ne connaît pas le modèle « {model} ». "
            "`nikoforge doctor` liste ce qu'il annonce."
        )
    if status == 400 and (
        "context" in lowered or "too long" in lowered or "n_ctx" in lowered
    ):
        return ContextTooLong(
            f"la requête dépasse la fenêtre de contexte du serveur : {message[:200]}. "
            "Réduisez llm.max_tokens ou context.max_tokens."
        )
    if status is not None and 500 <= int(status) < 600:
        return ServerError(
            f"le serveur a renvoyé une erreur {status} : {message[:200]}"
        )
    return LLMError(f"erreur d'accès au modèle : {message[:300]}")
