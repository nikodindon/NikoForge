"""``nikoforge doctor`` : diagnostic de l'installation.

Répond à une seule question : « qu'est-ce qui empêche NikoForge de fonctionner ? ».
Chaque contrôle indique soit que tout va bien, soit **ce qu'il faut corriger**.

Le code de sortie est exploitable : ``0`` si aucun contrôle critique n'échoue, ``1`` sinon.
C'est le premier pas vers le correctif C17 (le CLI de la v2 sortait toujours en 0).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .config import Config, data_dir, state_dir, user_config_path
from .server import (
    Probe,
    pick_model,
    port_of,
    probe,
    server_context_size,
    suggest_server_command,
)

#: Version minimale de Python, alignée sur ``requires-python`` de pyproject.toml.
MINIMUM_PYTHON = (3, 11)

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARKERS = {OK: "✔", WARN: "⚠", FAIL: "✖"}


@dataclass
class Check:
    """Un point de contrôle et son verdict."""

    label: str
    status: str
    detail: str = ""
    remedy: str = ""

    @property
    def critical(self) -> bool:
        return self.status == FAIL

    def render(self) -> str:
        line = f"{_MARKERS[self.status]} {self.label:<14} {self.detail}".rstrip()
        if self.remedy:
            line += "\n" + "\n".join(f"  → {part}" for part in self.remedy.splitlines())
        return line


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if check.status == WARN]

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def render(self) -> str:
        lines = [check.render() for check in self.checks]

        if self.failed:
            lines.append("")
            lines.append(
                f"{len(self.failed)} problème(s) bloquant(s). "
                "Corrigez les points marqués ✖ puis relancez `nikoforge doctor`."
            )
        elif self.warnings:
            lines.append("")
            lines.append("Tout est opérationnel (avertissements non bloquants ci-dessus).")
        else:
            lines.append("")
            lines.append("Tout est opérationnel.")

        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Contrôles unitaires
# --------------------------------------------------------------------------- #


def check_python() -> Check:
    version = sys.version_info
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < MINIMUM_PYTHON:
        minimum = ".".join(str(part) for part in MINIMUM_PYTHON)
        return Check(
            "python",
            FAIL,
            detail,
            f"NikoForge demande Python {minimum} ou plus récent.",
        )
    return Check("python", OK, detail)


def check_package() -> Check:
    try:
        import openai  # noqa: F401
    except ImportError:
        return Check(
            "paquet",
            FAIL,
            f"nikoforge {__version__}, dépendance `openai` absente",
            'pip install "nikoforge"  (ou pip install openai)',
        )
    return Check("paquet", OK, f"nikoforge {__version__}")


def check_config(config: Config) -> Check:
    if config.source is None:
        return Check(
            "config",
            OK,
            f"aucun fichier, valeurs par défaut ({user_config_path()} absent)",
        )
    return Check("config", OK, str(config.source))


def check_workdir(config: Config) -> Check:
    workdir = config.workdir
    if not workdir.exists():
        return Check(
            "workdir",
            FAIL,
            f"{workdir} (inexistant)",
            f"mkdir -p {workdir}",
        )
    if not workdir.is_dir():
        return Check("workdir", FAIL, f"{workdir} n'est pas un répertoire")
    if not _is_writable(workdir):
        return Check(
            "workdir",
            FAIL,
            f"{workdir} (lecture seule)",
            "L'agent ne pourra ni écrire ni modifier de fichier ici. Vérifiez les droits.",
        )
    return Check("workdir", OK, str(workdir))


def _is_writable(directory: Path) -> bool:
    probe_file = directory / ".nikoforge-write-test"
    try:
        probe_file.write_text("", encoding="utf-8")
    except OSError:
        return False
    finally:
        try:
            probe_file.unlink()
        except OSError:
            pass
    return True


def check_tools() -> Check:
    """Vérifie que les outils attendus existent réellement sur la classe ``Tools``."""
    from .tools import Tools

    expected = ("read_file", "write_file", "edit_file", "bash", "list_files")
    missing = [name for name in expected if not callable(getattr(Tools, name, None))]
    if missing:
        return Check(
            "outils",
            FAIL,
            f"absent(s) : {', '.join(missing)}",
            "Installation incomplète ou corrompue — réinstallez nikoforge.",
        )
    return Check("outils", OK, ", ".join(expected))


def check_skills(config: Config) -> Check:
    """Les skills sont lus dans le répertoire de travail (leur chargement réel arrive en phase 4)."""
    directory = config.workdir / "skills"
    if not directory.is_dir():
        return Check("skills", WARN, f"pas de répertoire {directory}")
    names = sorted(path.stem for path in directory.glob("*.md") if path.name != "README.md")
    if not names:
        return Check("skills", WARN, f"{directory} : 0 skill")
    return Check(
        "skills",
        WARN,
        f"{len(names)} présent(s), chargement en phase 4 : {', '.join(names)}",
    )


def check_storage() -> Check:
    return Check(
        "stockage",
        OK,
        f"{data_dir()} · {state_dir()}",
    )


def check_server(config: Config) -> tuple[Check, Probe]:
    base_url = config.llm.base_url
    result = probe(base_url)

    if not result.ok:
        return (
            Check(
                "serveur",
                FAIL,
                f"{base_url} — {result.error}",
                f"{result.detail}\n{suggest_server_command(base_url)}",
            ),
            result,
        )

    latency = f" ({result.latency * 1000:.0f} ms)" if result.latency else ""
    return Check("serveur", OK, f"{base_url}{latency} — {result.detail}"), result


def check_model(config: Config, result: Probe) -> Check:
    if config.llm.model:
        if result.ok and result.models and config.llm.model not in result.models:
            return Check(
                "modèle",
                WARN,
                f"{config.llm.model} (non annoncé par le serveur)",
                "Le serveur répond mais n'annonce pas ce modèle. Le nom doit être exact, "
                "ou laissez-le vide pour le découvrir automatiquement.",
            )
        return Check("modèle", OK, config.llm.model)

    if not result.ok:
        return Check("modèle", WARN, "indéterminé (serveur injoignable)")

    model, warning = pick_model(result)
    if model is None:
        return Check(
            "modèle",
            FAIL,
            "aucun modèle annoncé par le serveur",
            "Chargez un modèle : llama-server -m /chemin/vers/modele.gguf",
        )
    if warning:
        return Check("modèle", WARN, warning)
    return Check("modèle", OK, f"{model} (découvert)")


def check_context(config: Config, result: Probe) -> Check:
    announced = server_context_size(config.llm.base_url) if result.ok else None
    configured = config.context.max_tokens

    if announced is None:
        return Check("contexte", OK, f"{configured} tokens (non vérifiable côté serveur)")
    if configured > announced:
        return Check(
            "contexte",
            WARN,
            f"{configured} configurés > {announced} annoncés par le serveur",
            "Les échanges dépasseront la fenêtre du serveur et seront tronqués en silence.\n"
            f"Aligner : nikoforge --context {announced}",
        )
    return Check("contexte", OK, f"{configured} tokens (serveur : {announced})")


# --------------------------------------------------------------------------- #
# Rapport complet
# --------------------------------------------------------------------------- #


def run_doctor(config: Config) -> Report:
    """Exécute tous les contrôles. Aucune impression : le rendu est fait par l'appelant."""
    report = Report()

    report.checks.append(check_python())
    report.checks.append(check_package())
    report.checks.append(check_config(config))

    server_check, result = check_server(config)
    report.checks.append(server_check)
    report.checks.append(check_model(config, result))
    report.checks.append(check_context(config, result))

    report.checks.append(check_tools())
    report.checks.append(check_skills(config))
    report.checks.append(check_workdir(config))
    report.checks.append(check_storage())

    return report


def render_summary_line(config: Config, report: Report) -> str:
    """Ligne d'en-tête du rapport, avec le port effectif."""
    status = "prêt" if report.exit_code == 0 else "non opérationnel"
    return (
        f"nikoforge {__version__} — {status}\n"
        f"serveur {config.llm.base_url} (port {port_of(config.llm.base_url)}) · "
        f"config {config.describe_source()}"
    )
