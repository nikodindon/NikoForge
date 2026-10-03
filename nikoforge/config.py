"""Configuration de NikoForge.

Précédence, du moins prioritaire au plus prioritaire :

1. **les valeurs par défaut**, définies en dur ci-dessous — elles sont complètes, donc
   *le fichier de configuration est optionnel*. C'est le point qui débloque le bloquant B1
   de la v2 (où un ``config.json`` obligatoire et absent empêchait tout démarrage) ;
2. le **fichier TOML** de l'utilisateur (``$NIKOFORGE_CONFIG`` ou
   ``$XDG_CONFIG_HOME/nikoforge/config.toml``) ;
3. les **variables d'environnement** (``NIKOFORGE_BASE_URL``, ``NIKOFORGE_MODEL``, …) ;
4. les **arguments de la ligne de commande**.

Aucune de ces couches n'est obligatoire. ``nikoforge`` doit pouvoir démarrer sur une machine
vierge où seul un ``llama-server`` écoute sur le port par défaut (D6 de ``docs/DECISIONS.md``).
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "nikoforge"

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_API_KEY = "sk-dummy"
DEFAULT_ENV_FILE = "NIKOFORGE_CONFIG"

#: Variable d'environnement -> (section, champ) de la configuration.
ENV_VARS: dict[str, tuple[str, str]] = {
    "NIKOFORGE_BASE_URL": ("llm", "base_url"),
    "NIKOFORGE_MODEL": ("llm", "model"),
    "NIKOFORGE_API_KEY": ("llm", "api_key"),
    "NIKOFORGE_TEMPERATURE": ("llm", "temperature"),
    "NIKOFORGE_MAX_TOKENS": ("llm", "max_tokens"),
    "NIKOFORGE_TIMEOUT": ("llm", "timeout"),
    "NIKOFORGE_PROTOCOL": ("llm", "protocol"),
    "NIKOFORGE_ENABLE_THINKING": ("llm", "enable_thinking"),
    "NIKOFORGE_CONTEXT": ("context", "max_tokens"),
    "NIKOFORGE_COMPACTION_THRESHOLD": ("context", "compaction_threshold"),
    "NIKOFORGE_SUMMARY_TOKENS": ("context", "summary_tokens"),
    "NIKOFORGE_MAX_ITERATIONS": ("agent", "max_iterations"),
    "NIKOFORGE_TOOL_TIMEOUT": ("agent", "tool_timeout"),
}

#: Valeurs textuelles interprétées comme « pas de limite » (0) pour un champ numérique.
_NO_LIMIT_LITERALS = {"", "none", "null", "unlimited"}

#: Champs à valeurs fermées : une faute de frappe doit être signalée, pas interprétée.
CHOICES: dict[tuple[str, str], tuple[str, ...]] = {
    ("llm", "protocol"): ("auto", "native", "text"),
}


class ConfigError(Exception):
    """Configuration invalide ou introuvable. Le message est destiné à l'utilisateur."""


# --------------------------------------------------------------------------- #
# Modèle
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LLMConfig:
    """Accès au serveur d'inférence compatible OpenAI."""

    base_url: str = DEFAULT_BASE_URL
    #: Vide = découverte automatique via ``GET /v1/models`` (utile avec llama-server,
    #: dont l'identifiant de modèle est le chemin du fichier GGUF).
    model: str = ""
    api_key: str = DEFAULT_API_KEY
    temperature: float = 0.7
    max_tokens: int = 8192
    #: ``300.0`` par défaut : une génération doit finir ou échouer, pas bloquer indéfiniment.
    #: ``0`` signifie « pas de limite » — TOML n'ayant pas de valeur nulle, c'est la seule
    #: façon d'exprimer cela dans le fichier, et c'est plus lisible que ``null``.
    timeout: float = 300.0
    #: ``auto`` = protocole natif si le serveur l'annonce (``/props``), textuel sinon.
    #: ``native`` et ``text`` forcent l'un ou l'autre.
    protocol: str = "auto"
    #: Séquences d'arrêt transmises au serveur.
    stop: list[str] = field(default_factory=list)
    #: Certains modèles (Qwen3) consomment beaucoup de contexte en réflexion. Désactivée par
    #: défaut : le raisonnement est alors conservé à part au lieu d'être renvoyé au modèle.
    enable_thinking: bool = False


@dataclass(frozen=True)
class ContextConfig:
    """Budget de contexte et politique de compaction."""

    max_tokens: int = 32768
    #: Fraction de ``max_tokens`` au-delà de laquelle la compaction se déclenche.
    compaction_threshold: float = 0.8
    summary_tokens: int = 1000


@dataclass(frozen=True)
class AgentConfig:
    """Limites d'exécution de la boucle."""

    max_iterations: int = 20
    tool_timeout: int = 600


@dataclass(frozen=True)
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    #: Répertoire de travail de l'agent (celui dans lequel il lit et écrit).
    workdir: Path = field(default_factory=Path.cwd)
    #: Fichier TOML réellement chargé, ou ``None`` si l'on tourne sur les seuls défauts.
    source: Path | None = None

    def describe_source(self) -> str:
        """Description lisible de la provenance de la configuration."""
        return str(self.source) if self.source else "(valeurs par défaut, aucun fichier)"


SECTIONS: dict[str, type] = {
    "llm": LLMConfig,
    "context": ContextConfig,
    "agent": AgentConfig,
}

SECTION_COMMENTS: dict[str, str] = {
    "llm": "Serveur d'inference (llama-server ou tout autre endpoint compatible OpenAI)",
    "context": "Budget de contexte et declenchement de la compaction",
    "agent": "Limites d'execution de la boucle de l'agent",
}

FIELD_COMMENTS: dict[tuple[str, str], str] = {
    ("llm", "base_url"): "URL du serveur, terminee par /v1",
    ("llm", "model"): "Nom du modele. Vide = decouvert via GET /v1/models",
    ("llm", "api_key"): "Cle d'API. Ignoree par llama-server, mais requise par le client",
    ("llm", "temperature"): "0.0 = deterministe, 1.0 = creatif",
    ("llm", "max_tokens"): "Longueur maximale d'une reponse du modele",
    ("llm", "timeout"): "Delai maximal en secondes. 0 = pas de limite",
    ("llm", "protocol"): "auto = natif si le serveur l'annonce, sinon textuel (auto|native|text)",
    ("llm", "stop"): "Sequences d'arret envoyees au serveur",
    ("llm", "enable_thinking"): "false = raisonnement desactive et garde a part",
    ("context", "max_tokens"): "Fenetre de contexte annoncee par le serveur",
    ("context", "compaction_threshold"): "Fraction de max_tokens declenchant la compaction",
    ("context", "summary_tokens"): "Taille visee pour le resume de compaction",
    ("agent", "max_iterations"): "Nombre maximal d'allers-retours par tache",
    ("agent", "tool_timeout"): "Delai maximal par commande shell, en secondes",
}


def default_config(workdir: Path | None = None) -> Config:
    """Configuration entièrement par défaut. Aucun accès disque."""
    return Config(workdir=Path(workdir) if workdir else Path.cwd())


# --------------------------------------------------------------------------- #
# Emplacements XDG
# --------------------------------------------------------------------------- #


def _xdg(
    env_var: str, fallback: Path, env: Mapping[str, str] | None = None
) -> Path:
    """Résout un répertoire XDG, en respectant l'environnement fourni.

    Le paramètre ``env`` explicite est ce qui rend les tests hermétiques : sans lui, ils
    liraient la vraie configuration de la machine qui exécute la suite.
    """
    environ = os.environ if env is None else env
    raw_home = environ.get("HOME")
    home = Path(raw_home) if raw_home else Path.home()

    raw = environ.get(env_var)
    base = Path(raw) if raw else home / fallback
    return base / APP_NAME


def user_config_path(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_CONFIG_HOME/nikoforge/config.toml`` (défaut ``~/.config/nikoforge/config.toml``)."""
    return _xdg("XDG_CONFIG_HOME", Path(".config"), env) / "config.toml"


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    """Données persistantes (sessions). Utilisé à partir de la phase 5."""
    return _xdg("XDG_DATA_HOME", Path(".local/share"), env)


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    """État local (journaux, points de restauration). Utilisé à partir de la phase 5."""
    return _xdg("XDG_STATE_HOME", Path(".local/state"), env)


def find_config_file(
    explicit: str | Path | None = None, env: Mapping[str, str] | None = None
) -> Path | None:
    """Résout le fichier de configuration à charger.

    Un chemin demandé **explicitement** (``--config`` ou ``$NIKOFORGE_CONFIG``) doit
    exister : le silence sur un chemin fautif est un piège classique.
    Le fichier utilisateur par défaut, lui, est facultatif.
    """
    environ = os.environ if env is None else env

    for candidate, origin in (
        (explicit, "--config"),
        (environ.get(DEFAULT_ENV_FILE), f"${DEFAULT_ENV_FILE}"),
    ):
        if candidate:
            path = Path(candidate).expanduser()
            if not path.is_file():
                raise ConfigError(f"{origin} : fichier introuvable — {path}")
            return path

    default = user_config_path(environ)
    return default if default.is_file() else None


# --------------------------------------------------------------------------- #
# Conversion de types
# --------------------------------------------------------------------------- #


def _as_float(value: Any) -> float:
    """Convertit en flottant ; une chaîne vide ou ``none``/``null`` vaut ``0``.

    Convention : ``0`` signifie « pas de limite » (voir ``LLMConfig.timeout``).
    """
    if isinstance(value, str) and value.strip().lower() in _NO_LIMIT_LITERALS:
        return 0.0
    return float(value)


def _coerce(value: Any, hint: Any, where: str) -> Any:
    """Convertit ``value`` vers le type ``hint``, avec des messages d'erreur utilisables.

    Nécessaire parce que les variables d'environnement sont toujours des chaînes, alors que
    le TOML apporte déjà les bons types.
    """
    origin = typing.get_origin(hint)

    if origin is list:
        arguments = typing.get_args(hint)
        inner = arguments[0] if arguments else str
        if isinstance(value, str):
            # Une variable d'environnement ne peut porter qu'une valeur : on l'accepte seule.
            return [_coerce(value, inner, f"{where}[0]")]
        if not isinstance(value, (list, tuple)):
            raise ConfigError(
                f"{where} : liste attendue, reçu {type(value).__name__}"
            )
        return [_coerce(item, inner, f"{where}[{index}]") for index, item in enumerate(value)]

    try:
        if hint is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "oui", "on"}
        if hint is int:
            if isinstance(value, bool):
                raise ValueError("booléen reçu là où un entier est attendu")
            return int(value)
        if hint is float:
            return _as_float(value)
        if hint is str:
            return str(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where} : valeur invalide {value!r} ({exc})") from exc

    return value


def _check_choices(section: str, values: Mapping[str, Any]) -> None:
    for (candidate_section, key), allowed in CHOICES.items():
        if candidate_section != section or key not in values:
            continue
        if values[key] not in allowed:
            raise ConfigError(
                f"[{section}] {key} : {values[key]!r} invalide. "
                f"Valeurs acceptées : {', '.join(allowed)}"
            )


def _section_types(section: str) -> dict[str, Any]:
    return typing.get_type_hints(SECTIONS[section])


def _merge_section(section: str, data: Any) -> Any:
    cls = SECTIONS[section]
    if not isinstance(data, Mapping):
        raise ConfigError(
            f"[{section}] doit être une table TOML, reçu {type(data).__name__}"
        )

    hints = _section_types(section)
    unknown = sorted(set(data) - set(hints))
    if unknown:
        known = ", ".join(sorted(hints))
        raise ConfigError(
            f"clé inconnue dans [{section}] : {', '.join(unknown)}. Clés valides : {known}"
        )

    kwargs = {
        key: _coerce(value, hints[key], f"[{section}] {key}") for key, value in data.items()
    }
    _check_choices(section, kwargs)
    return cls(**kwargs)


def config_from_mapping(
    data: Mapping[str, Any], source: Path | None = None, workdir: Path | None = None
) -> Config:
    """Construit une ``Config`` à partir d'un tableau associatif (issu du TOML), sur les défauts."""
    unknown = sorted(set(data) - set(SECTIONS))
    if unknown:
        raise ConfigError(
            f"section inconnue dans {source or 'la configuration'} : {', '.join(unknown)}. "
            f"Sections valides : {', '.join(sorted(SECTIONS))}"
        )

    kwargs: dict[str, Any] = {
        name: _merge_section(name, data[name]) for name in SECTIONS if name in data
    }
    config = dataclasses.replace(default_config(workdir), **kwargs)
    return dataclasses.replace(config, source=source)


def apply_env(config: Config, env: Mapping[str, str] | None = None) -> Config:
    """Applique les variables d'environnement au-dessus du fichier."""
    environ = os.environ if env is None else env

    updates: dict[str, dict[str, Any]] = {}
    for variable, (section, key) in ENV_VARS.items():
        if variable not in environ:
            continue
        hint = _section_types(section)[key]
        updates.setdefault(section, {})[key] = _coerce(
            environ[variable], hint, f"${variable}"
        )

    if not updates:
        return config

    sections = {name: getattr(config, name) for name in SECTIONS}
    for section, values in updates.items():
        sections[section] = dataclasses.replace(sections[section], **values)
    return dataclasses.replace(config, **sections)


def apply_overrides(config: Config, overrides: Mapping[str, Any] | None) -> Config:
    """Applique les arguments de la ligne de commande (couche de plus haute priorité).

    ``overrides`` est un tableau ``{section: {champ: valeur}}``, plus la clé optionnelle
    ``workdir``. Les valeurs ``None`` sont ignorées : un argument CLI non fourni ne doit pas
    écraser une valeur venue du fichier.
    """
    if not overrides:
        return config

    sections = {name: getattr(config, name) for name in SECTIONS}
    changed = False

    for key, value in overrides.items():
        if key == "workdir":
            continue
        if key not in SECTIONS:
            raise ConfigError(f"override inconnu : {key}")
        values = {k: v for k, v in (value or {}).items() if v is not None}
        if not values:
            continue
        hints = _section_types(key)
        unknown = sorted(set(values) - set(hints))
        if unknown:
            raise ConfigError(f"override inconnu dans {key} : {', '.join(unknown)}")
        coerced = {k: _coerce(v, hints[k], f"{key}.{k}") for k, v in values.items()}
        _check_choices(key, coerced)
        sections[key] = dataclasses.replace(sections[key], **coerced)
        changed = True

    result = dataclasses.replace(config, **sections) if changed else config

    workdir = overrides.get("workdir")
    if workdir:
        result = dataclasses.replace(result, workdir=Path(workdir).expanduser())
    return result


def load_config(
    explicit: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Charge la configuration effective, en appliquant les quatre couches de précédence."""
    environ = os.environ if env is None else env
    path = find_config_file(explicit, environ)

    data: Mapping[str, Any] = {}
    if path is not None:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} : TOML invalide — {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"{path} : lecture impossible — {exc}") from exc

    config = config_from_mapping(data, source=path)
    config = apply_env(config, environ)
    return apply_overrides(config, overrides)


# --------------------------------------------------------------------------- #
# Sérialisation TOML
# --------------------------------------------------------------------------- #


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _toml_string(value)
    return repr(value)


def render_toml(config: Config, header: bool = True) -> str:
    """Rend la configuration en TOML **commenté et complet**.

    Le résultat est ré-analysable sans perte : ``render_toml`` puis ``load_config`` redonne
    une configuration identique (test ``test_render_toml_round_trip``).
    """
    lines: list[str] = []

    if header:
        lines += [
            "# Configuration NikoForge.",
            "#",
            "# Genere par `nikoforge init`. Toutes les valeurs sont optionnelles :",
            "# ce fichier peut etre supprime, les defauts du programme s'appliquent.",
            "#",
            "# Precedence : defauts < ce fichier < variables d'environnement < arguments CLI.",
            "# Vue complete et a jour : nikoforge --print-config",
            "",
        ]

    for section in ("llm", "context", "agent"):
        lines.append(f"# {SECTION_COMMENTS[section]}")
        lines.append(f"[{section}]")
        for field_info in dataclasses.fields(SECTIONS[section]):
            value = getattr(getattr(config, section), field_info.name)
            comment = FIELD_COMMENTS.get((section, field_info.name))
            if comment:
                lines.append(f"# {comment}")
            lines.append(f"{field_info.name} = {_toml_value(value)}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_config(config: Config, path: Path) -> Path:
    """Écrit la configuration en TOML. Crée les répertoires parents si besoin.

    L'écriture passe par un fichier temporaire puis ``os.replace`` : une interruption ne
    laisse jamais un fichier de configuration tronqué.
    """
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(render_toml(config), encoding="utf-8")
    os.replace(temporary, path)
    return path
