"""Codage et décodage des appels d'outils.

Deux protocoles coexistent, et **les deux sont acceptés en lecture** :

1. **natif** — le champ ``tools`` de l'API OpenAI, réponse en ``tool_calls`` structurés.
   C'est le chemin nominal : aucun texte à interpréter, donc aucune classe de bugs de parsing.
2. **texte** — des balises dans le contenu de la réponse, contenu encodé en CDATA.
   Nécessaire pour tout serveur qui n'implémente pas ``tools``.

La détection se fait sur ``GET /props`` → ``chat_template_caps.supports_tools``. Le champ
``capabilities`` de ``GET /v1/models`` n'est **pas** fiable : le serveur de référence de ce
projet annonce ``["completion"]`` tout en acceptant parfaitement ``tools`` (mesuré le
2026-10-03). Voir ``docs/DECISIONS.md``, D1.

Ce module est **pur** : aucune entrée/sortie, aucun réseau, aucun état global. C'est ce qui
permet de le tester exhaustivement, y compris sur ce qui cassait la v2 : du contenu généré
contenant ``</tool>``, de l'indentation, des entités XML, du CDATA.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

CDATA_OPEN = "<![CDATA["
CDATA_CLOSE = "]]>"

TOOL_CALLS_OPEN = "<tool_calls"
TOOL_CALLS_CLOSE = "</tool_calls>"
TOOL_OPEN = "<tool"
TOOL_CLOSE = "</tool>"
PARAM_OPEN = "<param"
PARAM_CLOSE = "</param>"

#: Caractères qui imposent l'encodage en CDATA (sinon la valeur serait ambiguë).
_NEEDS_CDATA = ("<", ">", "&")

_ENTITIES = {"lt": "<", "gt": ">", "quot": '"', "apos": "'", "amp": "&"}
_ENTITY_RE = re.compile(r"&(lt|gt|quot|apos|amp);")


# --------------------------------------------------------------------------- #
# Schéma des outils
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Parameter:
    """Un paramètre d'outil. Sert au prompt, au schéma natif **et** à la validation."""

    name: str
    type: str  # "string" | "integer" | "number"
    description: str
    required: bool = True


@dataclass(frozen=True)
class ToolSpec:
    """Spécification complète d'un outil : une seule source de vérité.

    Le prompt envoyé au modèle, le tableau ``tools`` de l'API OpenAI et la validation des
    arguments sont tous dérivés d'ici. En v2, ces trois choses étaient écrites séparément et
    avaient divergé : le prompt annonçait ``read_file(path)`` pendant que le routeur acceptait
    silencieusement ``read_file(raw=...)`` (bug C15a).
    """

    name: str
    description: str
    parameters: tuple[Parameter, ...] = ()

    def parameter(self, name: str) -> Parameter | None:
        for candidate in self.parameters:
            if candidate.name == name:
                return candidate
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters if parameter.required)

    def render_prompt(self) -> str:
        """Ligne du prompt système, par exemple ``- bash(command, timeout)``."""
        signature = ", ".join(self.names)
        return f"- {self.name}({signature}) → {self.description}"

    def to_openai_schema(self) -> dict[str, Any]:
        """Forme attendue par le champ ``tools`` de l'API OpenAI."""
        properties: dict[str, Any] = {}
        for parameter in self.parameters:
            entry: dict[str, Any] = {"type": parameter.type, "description": parameter.description}
            properties[parameter.name] = entry
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(self.required),
                },
            },
        }


#: Les cinq outils, déclarés une fois. Phase 4 en fera un registre extensible.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "list_files",
        "Liste les fichiers d'un répertoire",
        (Parameter("path", "string", "Répertoire à lister", required=False),),
    ),
    ToolSpec(
        "read_file",
        "Lit un fichier texte",
        (Parameter("path", "string", "Chemin du fichier"),),
    ),
    ToolSpec(
        "write_file",
        "Crée ou remplace un fichier",
        (
            Parameter("path", "string", "Chemin du fichier"),
            Parameter("content", "string", "Contenu complet à écrire"),
        ),
    ),
    ToolSpec(
        "edit_file",
        "Remplace un motif unique par un autre dans un fichier",
        (
            Parameter("path", "string", "Chemin du fichier"),
            Parameter("old_content", "string", "Motif à remplacer, doit être unique"),
            Parameter("new_content", "string", "Remplacement (chaîne vide pour supprimer)"),
        ),
    ),
    ToolSpec(
        "bash",
        "Exécute une commande shell",
        (
            Parameter("command", "string", "Commande à exécuter"),
            Parameter("timeout", "integer", "Délai maximal en secondes", required=False),
        ),
    ),
)

SPECS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}


def render_tools_for_prompt(specs: Sequence[ToolSpec] = TOOL_SPECS) -> str:
    return "\n".join(spec.render_prompt() for spec in specs)


def openai_tools(specs: Sequence[ToolSpec] = TOOL_SPECS) -> list[dict[str, Any]]:
    return [spec.to_openai_schema() for spec in specs]


# --------------------------------------------------------------------------- #
# Résultats
# --------------------------------------------------------------------------- #


class ProtocolError(Exception):
    """Un appel d'outil est inexploitable (arguments illisibles, JSON invalide…)."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    def __str__(self) -> str:  # pragma: no cover - confort de journalisation
        rendered = ", ".join(f"{key}={value!r}" for key, value in self.arguments.items())
        return f"{self.name}({rendered})"


@dataclass(frozen=True)
class TextParse:
    """Résultat du décodage de la forme textuelle."""

    text: str
    calls: tuple[ToolCall, ...] = ()
    #: Un bloc ``<tool_calls>`` a été ouvert sans être refermé — typiquement une réponse
    #: coupée par ``max_tokens``. Le texte est conservé tel quel, rien n'est deviné.
    incomplete: bool = False


@dataclass(frozen=True)
class ParsedResponse:
    """Une réponse de modèle réduite à ce dont l'agent a besoin."""

    text: str = ""
    reasoning: str = ""
    calls: tuple[ToolCall, ...] = ()
    incomplete: bool = False


# --------------------------------------------------------------------------- #
# Décodage de la forme textuelle
# --------------------------------------------------------------------------- #


def _attribute(header: str, name: str) -> str | None:
    """Lit ``name="valeur"`` (ou ``name='valeur'``) dans un en-tête de balise.

    Les deux types de guillemets sont acceptés. La v2 exigeait les guillemets doubles et
    ignorait silencieusement tout le reste : un modèle qui utilisait ``name='x'`` produisait
    zéro appel, sans le moindre message.
    """
    pattern = re.compile(rf"""{name}\s*=\s*(?:"([^"]*)"|'([^']*)')""")
    match = pattern.search(header)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _decode_entities(value: str) -> str:
    """Décode les entités XML en une seule passe (``&amp;lt;`` → ``&lt;``, pas ``<``)."""
    return _ENTITY_RE.sub(lambda match: _ENTITIES[match.group(1)], value)


def _normalise(value: str) -> str:
    """Retire **un seul** saut de ligne de tête et de queue, jamais d'espace.

    Nécessaire parce qu'un modèle écrit naturellement::

        <param name="content">
        du texte
        </param>

    La v2 appliquait ``.strip()`` à *tous* les paramètres : l'indentation de la première ligne
    et le saut de ligne final disparaissaient, ce qui produisait des fichiers Python qui ne
    compilaient pas (bug C1b). Ici les espaces et tabulations ne sont jamais touchés, et le
    contenu en CDATA n'est pas normalisé du tout.
    """
    if value.startswith("\r\n"):
        value = value[2:]
    elif value.startswith("\n"):
        value = value[1:]
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    return value


def _scan_params(text: str, start: int) -> tuple[dict[str, str], int | None]:
    """Lit les ``<param>`` à partir de ``start``, jusqu'à ``</tool>``.

    Retourne ``(arguments, position_apres_le_tool)``. ``position`` vaut ``None`` quand la
    balise ``</tool>`` est absente — réponse coupée par ``max_tokens`` — et l'appel est alors
    considéré comme inexploitable : mieux vaut ne rien exécuter qu'écrire un fichier tronqué.

    Cette fonction est le cœur de la correction de C1a. Elle ne cherche jamais un délimiteur
    « à l'aveugle » : chaque paramètre est consommé **en entier**, CDATA compris. Un ``</tool>``
    présent à l'intérieur d'une valeur ne peut donc pas terminer le corps de la balise, ce que
    faisait l'expression régulière de la v2.
    """
    arguments: dict[str, str] = {}
    cursor = start
    length = len(text)

    while cursor < length:
        param_position = text.find(PARAM_OPEN, cursor)
        tool_close = text.find(TOOL_CLOSE, cursor)

        if tool_close != -1 and (param_position == -1 or tool_close < param_position):
            return arguments, tool_close + len(TOOL_CLOSE)
        if param_position == -1:
            return arguments, None

        after = param_position + len(PARAM_OPEN)
        if after < length and text[after] not in " \t\r\n>":
            cursor = after
            continue
        open_end = text.find(">", after)
        if open_end == -1:
            return arguments, None

        name = _attribute(text[after:open_end], "name")
        value_start = open_end + 1

        if text.startswith(CDATA_OPEN, value_start):
            # Contenu brut : rien n'y est interprété, ni balise, ni entité.
            content_start = value_start + len(CDATA_OPEN)
            cdata_end = text.find(CDATA_CLOSE, content_start)
            if cdata_end == -1:
                return arguments, None
            if name:
                arguments[name] = text[content_start:cdata_end]
            close = text.find(PARAM_CLOSE, cdata_end + len(CDATA_CLOSE))
            if close == -1:
                return arguments, None
            cursor = close + len(PARAM_CLOSE)
        else:
            close = text.find(PARAM_CLOSE, value_start)
            if close == -1:
                return arguments, None
            if name:
                arguments[name] = _normalise(_decode_entities(text[value_start:close]))
            cursor = close + len(PARAM_CLOSE)

    return arguments, None


def _scan_block(text: str, start: int, length: int) -> tuple[list[ToolCall], int | None]:
    """Lit les ``<tool>`` d'un bloc, jusqu'à ``</tool_calls>``."""
    calls: list[ToolCall] = []
    cursor = start

    while cursor < length:
        tool_position = text.find(TOOL_OPEN, cursor)
        block_close = text.find(TOOL_CALLS_CLOSE, cursor)

        if block_close != -1 and (tool_position == -1 or block_close < tool_position):
            return calls, block_close + len(TOOL_CALLS_CLOSE)
        if tool_position == -1:
            return calls, None

        after = tool_position + len(TOOL_OPEN)
        if after < length and text[after] not in " \t\r\n>":
            # ``<toolbox>``, ``<tools>``… ne sont pas des appels.
            cursor = after
            continue

        open_end = text.find(">", after)
        if open_end == -1:
            return calls, None

        name = _attribute(text[after:open_end], "name")
        arguments, end = _scan_params(text, open_end + 1)

        if end is None:
            # Appel tronqué : on n'exécute rien et on le signalera.
            return calls, None
        if name:
            calls.append(ToolCall(name=name, arguments=arguments))
        cursor = end

    return calls, None


def parse_text_calls(text: str) -> TextParse:
    """Extrait les appels d'outils écrits en balises et retire ces balises du texte.

    Le texte est renvoyé débarrassé des blocs d'outils : le message assistant conservé dans
    l'historique ne contient alors que ce que le modèle a réellement dit, sans le balisage.
    """
    calls: list[ToolCall] = []
    kept: list[str] = []
    cursor = 0
    incomplete = False
    length = len(text)

    while cursor < length:
        start = text.find(TOOL_CALLS_OPEN, cursor)
        if start == -1:
            kept.append(text[cursor:])
            break

        after = start + len(TOOL_CALLS_OPEN)
        if after < length and text[after] not in " \t\r\n>":
            kept.append(text[cursor:after])
            cursor = after
            continue

        open_end = text.find(">", after)
        if open_end == -1:
            incomplete = True
            kept.append(text[cursor:])
            break

        found, position = _scan_block(text, open_end + 1, length)
        kept.append(text[cursor:start])
        calls.extend(found)

        if position is None:
            incomplete = True
            # Le balisage est conservé : le modèle doit voir sa propre coupure pour la
            # corriger au tour suivant.
            kept.append(text[start:])
            break

        cursor = position

    return TextParse(text="".join(kept).strip(), calls=tuple(calls), incomplete=incomplete)


# --------------------------------------------------------------------------- #
# Encodage de la forme textuelle
# --------------------------------------------------------------------------- #


def _encode_entities(value: str) -> str:
    """Échappement de repli quand le CDATA est impossible (contenu contenant ``]]>``)."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def encode_value(value: Any) -> str:
    """Encode une valeur de paramètre.

    Le CDATA est utilisé dès que la valeur contient un caractère ambigu, et c'est le cas
    général : un contenu de fichier peut contenir ``</param>``, ``</tool>``, ``<![CDATA[``…
    Dans un CDATA rien n'est interprété, donc rien ne peut casser le découpage. C'est ce qui
    supprime la classe de bugs C1a.
    """
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    needs_cdata = (
        any(character in text for character in _NEEDS_CDATA)
        or "\n" in text
        or text != text.strip()
    )
    if not needs_cdata:
        return text
    if CDATA_CLOSE in text:
        # Un CDATA ne peut pas contenir « ]]> ». On replie sur les entités, que le décodeur
        # rétablit à l'identique (au prix de la normalisation d'un saut de ligne de bord).
        return _encode_entities(text)
    return f"{CDATA_OPEN}{text}{CDATA_CLOSE}"


def encode_text_call(call: ToolCall) -> str:
    """Rend un appel d'outil sous la forme textuelle balisée."""
    lines = [TOOL_CALLS_OPEN + ">", f'{TOOL_OPEN} name="{call.name}">']
    for key, value in call.arguments.items():
        lines.append(f'{PARAM_OPEN} name="{key}">{encode_value(value)}{PARAM_CLOSE}')
    lines.append(TOOL_CLOSE)
    lines.append(TOOL_CALLS_CLOSE)
    return "\n".join(lines)


def encode_text_calls(calls: Iterable[ToolCall]) -> str:
    return "\n".join(encode_text_call(call) for call in calls)


# --------------------------------------------------------------------------- #
# Forme native
# --------------------------------------------------------------------------- #


def parse_native_calls(raw_calls: Sequence[Any] | None) -> tuple[ToolCall, ...]:
    """Convertit les ``tool_calls`` renvoyés par l'API OpenAI en ``ToolCall``.

    Accepte les objets du SDK comme des dictionnaires, pour rester testable sans SDK.
    Des arguments qui ne sont pas du JSON valide lèvent ``ProtocolError`` : c'est une panne
    réelle, et l'agent doit pouvoir la signaler au modèle plutôt que de la masquer.
    """
    if not raw_calls:
        return ()

    calls: list[ToolCall] = []
    for raw in raw_calls:
        if isinstance(raw, Mapping):
            function = raw.get("function") or {}
            name = function.get("name") or raw.get("name")
            arguments = function.get("arguments")
            call_id = raw.get("id")
        else:
            function = getattr(raw, "function", None)
            name = getattr(function, "name", None) or getattr(raw, "name", None)
            arguments = getattr(function, "arguments", None)
            call_id = getattr(raw, "id", None)

        if not name:
            raise ProtocolError(f"appel d'outil sans nom : {raw!r}")

        if arguments is None or arguments == "":
            parsed: Mapping[str, Any] = {}
        elif isinstance(arguments, Mapping):
            parsed = arguments
        else:
            try:
                decoded = json.loads(arguments)
            except (TypeError, ValueError) as exc:
                raise ProtocolError(
                    f"arguments illisibles pour « {name} » ({exc}) : {str(arguments)[:200]!r}"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise ProtocolError(
                    f"arguments de « {name} » : objet JSON attendu, reçu {type(decoded).__name__}"
                )
            parsed = decoded

        calls.append(ToolCall(name=str(name), arguments=parsed, call_id=call_id))

    return tuple(calls)


def parse_response(
    content: str | None,
    native_calls: Sequence[Any] | None = None,
    reasoning: str = "",
) -> ParsedResponse:
    """Réduit une réponse de modèle à ``(texte, raisonnement, appels)``.

    Les appels natifs ont la priorité ; les blocs balisés sont malgré tout retirés du texte et
    leurs appels récupérés s'il n'y a pas de forme native. Un serveur peut donc basculer d'un
    protocole à l'autre, voire mélanger les deux, sans que l'agent ait à le savoir.
    """
    parsed_text = parse_text_calls(content or "")
    native = parse_native_calls(native_calls)

    calls = native if native else parsed_text.calls
    return ParsedResponse(
        text=parsed_text.text,
        reasoning=reasoning,
        calls=calls,
        incomplete=parsed_text.incomplete,
    )


# --------------------------------------------------------------------------- #
# Validation des arguments
# --------------------------------------------------------------------------- #


class ToolArgumentsError(ValueError):
    """Arguments refusés par le schéma. Le message est destiné au modèle **et** à l'humain."""


def validate_arguments(
    spec: ToolSpec, arguments: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Applique le schéma d'un outil et retourne les arguments normalisés.

    Remplace la validation de la v2, qui faisait ``if not all([path, old, new_content])`` :
    un test de vérité sur des chaînes, donc une ``new_content`` vide était refusée et
    **supprimer du texte était impossible** (bug C16). Ici, seule l'absence du paramètre est
    refusée, jamais une valeur vide.
    """
    provided = dict(arguments or {})

    unknown = sorted(set(provided) - set(spec.names))
    if unknown:
        raise ToolArgumentsError(
            f"paramètre(s) inconnu(s) pour {spec.name} : {', '.join(unknown)}. "
            f"Paramètres valides : {', '.join(spec.names) or '(aucun)'}"
        )

    resolved: dict[str, Any] = {}
    missing: list[str] = []

    for parameter in spec.parameters:
        if parameter.name not in provided:
            if parameter.required:
                missing.append(parameter.name)
            continue
        value = provided[parameter.name]
        if value is None and parameter.required:
            missing.append(parameter.name)
            continue
        resolved[parameter.name] = _coerce(parameter, value, spec.name)

    if missing:
        raise ToolArgumentsError(
            f"paramètre(s) manquant(s) pour {spec.name} : {', '.join(missing)}"
        )

    return resolved


def _coerce(parameter: Parameter, value: Any, tool: str) -> Any:
    if parameter.type == "integer":
        if isinstance(value, bool):
            raise ToolArgumentsError(
                f"{tool}.{parameter.name} : booléen reçu là où un entier est attendu"
            )
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ToolArgumentsError(
                f"{tool}.{parameter.name} : entier attendu, reçu {value!r}"
            ) from exc

    if parameter.type == "number":
        if isinstance(value, bool):
            raise ToolArgumentsError(
                f"{tool}.{parameter.name} : booléen reçu là où un nombre est attendu"
            )
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ToolArgumentsError(
                f"{tool}.{parameter.name} : nombre attendu, reçu {value!r}"
            ) from exc

    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ToolArgumentsError(
        f"{tool}.{parameter.name} : chaîne attendue, reçu {type(value).__name__}"
    )


def prepare_call(call: ToolCall, specs: Mapping[str, ToolSpec] | None = None) -> ToolCall:
    """Valide et normalise un appel. Lève ``ToolArgumentsError`` si le schéma est violé."""
    registry = SPECS_BY_NAME if specs is None else specs

    spec = registry.get(call.name)
    if spec is None:
        raise ToolArgumentsError(
            f"outil inconnu : « {call.name} ». Outils disponibles : "
            + ", ".join(sorted(registry))
        )

    return ToolCall(
        name=call.name,
        arguments=validate_arguments(spec, call.arguments),
        call_id=call.call_id,
    )
