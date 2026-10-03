"""NikoForge — agent de coding local pour llama-server (compatible OpenAI).

Source unique de vérité pour la version : ``pyproject.toml`` la lit via
``[tool.setuptools.dynamic] version = {attr = "nikoforge.__version__"}``.
"""

__version__ = "3.0.0.dev0"

__all__ = ["__version__", "Agent", "Config", "ToolResult", "Tools", "load_config"]


def __getattr__(name: str):
    """Import différé : ``import nikoforge`` ne doit pas charger ``openai``.

    Les commandes de diagnostic (``nikoforge doctor``, ``--version``) doivent fonctionner
    même si la dépendance ``openai`` est cassée ou absente — c'est précisément le cas
    qu'elles servent à diagnostiquer.
    """
    if name == "Agent":
        from .agent import Agent

        return Agent
    if name in {"Tools", "ToolResult"}:
        from . import tools

        return getattr(tools, name)
    if name == "Config":
        from .config import Config

        return Config
    if name == "load_config":
        from .config import load_config

        return load_config
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")
