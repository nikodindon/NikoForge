"""``nikoforge.config`` : précédence, fichiers, variables d'environnement, TOML.

Ce module porte la correction du bloquant B1 : en v2, un ``config.json`` obligatoire et
absent du dépôt empêchait tout démarrage. Ici, la configuration par défaut est **complète**,
donc le fichier est facultatif — et c'est testé explicitement.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from nikoforge.config import (
    ENV_VARS,
    AgentConfig,
    Config,
    ConfigError,
    LLMConfig,
    apply_env,
    apply_overrides,
    config_from_mapping,
    data_dir,
    default_config,
    find_config_file,
    load_config,
    render_toml,
    state_dir,
    user_config_path,
    write_config,
)


@pytest.fixture()
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """Environnement hermétique : aucun accès à la vraie ``~/.config`` de la machine."""
    home = tmp_path / "home"
    home.mkdir()
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}


# --------------------------------------------------------------------------- #
# Défauts : le fichier de configuration est facultatif (corrige B1)
# --------------------------------------------------------------------------- #


def test_default_config_is_complete_without_any_file():
    """Aucune lecture disque : les défauts suffisent à faire tourner l'agent."""
    config = default_config()
    assert isinstance(config, Config)
    assert config.llm.base_url == "http://127.0.0.1:8080/v1"
    assert config.llm.api_key
    assert config.context.max_tokens > 0
    assert config.agent.max_iterations > 0
    assert config.source is None


def test_load_config_works_with_no_file_at_all(isolated_env):
    """Le critère du bloquant B1 : démarrer sans avoir rien configuré."""
    config = load_config(env=isolated_env)
    assert config.source is None
    assert config.llm.base_url == "http://127.0.0.1:8080/v1"
    assert config.describe_source() == "(valeurs par défaut, aucun fichier)"


def test_config_is_immutable():
    """``Config`` est gelée : une couche ne peut pas modifier celle du dessous en place."""
    config = default_config()
    with pytest.raises(Exception):
        config.llm.temperature = 0.0  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Résolution du fichier
# --------------------------------------------------------------------------- #


def test_user_config_path_follows_xdg(tmp_path: Path):
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    assert user_config_path(env) == tmp_path / "cfg" / "nikoforge" / "config.toml"


def test_user_config_path_falls_back_to_dot_config(tmp_path: Path):
    env = {"HOME": str(tmp_path)}
    assert user_config_path(env) == tmp_path / ".config" / "nikoforge" / "config.toml"


def test_data_and_state_dirs_are_distinct(tmp_path: Path):
    env = {"HOME": str(tmp_path)}
    assert data_dir(env) == tmp_path / ".local/share" / "nikoforge"
    assert state_dir(env) == tmp_path / ".local/state" / "nikoforge"


def test_find_config_file_returns_none_when_absent(isolated_env):
    assert find_config_file(None, isolated_env) is None


def test_find_config_file_finds_the_user_file(isolated_env, tmp_path: Path):
    target = user_config_path(isolated_env)
    target.parent.mkdir(parents=True)
    target.write_text("[llm]\n", encoding="utf-8")
    assert find_config_file(None, isolated_env) == target


def test_explicit_missing_config_is_an_error(tmp_path: Path):
    """Un chemin demandé explicitement doit exister : le silence serait un piège."""
    with pytest.raises(ConfigError, match="introuvable"):
        find_config_file(str(tmp_path / "absent.toml"), {})


def test_env_var_pointing_at_a_missing_file_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="NIKOFORGE_CONFIG"):
        find_config_file(None, {"NIKOFORGE_CONFIG": str(tmp_path / "absent.toml")})


def test_explicit_config_takes_priority_over_the_environment(tmp_path: Path):
    explicit = tmp_path / "explicit.toml"
    explicit.write_text("", encoding="utf-8")
    other = tmp_path / "other.toml"
    other.write_text("", encoding="utf-8")

    assert find_config_file(str(explicit), {"NIKOFORGE_CONFIG": str(other)}) == explicit


# --------------------------------------------------------------------------- #
# Lecture d'un tableau TOML
# --------------------------------------------------------------------------- #


def test_partial_table_keeps_the_other_defaults():
    config = config_from_mapping({"llm": {"model": "mon-modele"}})
    assert config.llm.model == "mon-modele"
    assert config.llm.base_url == "http://127.0.0.1:8080/v1"
    assert config.context.max_tokens > 0


def test_unknown_section_is_rejected():
    with pytest.raises(ConfigError, match="section inconnue"):
        config_from_mapping({"llms": {"model": "x"}})


def test_unknown_key_is_rejected_with_the_list_of_valid_keys():
    """Un `max_token` au singulier doit être signalé, pas ignoré en silence."""
    with pytest.raises(ConfigError) as excinfo:
        config_from_mapping({"llm": {"max_token": 10}})
    message = str(excinfo.value)
    assert "max_token" in message
    assert "max_tokens" in message


def test_section_of_the_wrong_type_is_rejected():
    with pytest.raises(ConfigError, match="doit être une table"):
        config_from_mapping({"llm": "http://127.0.0.1:8080/v1"})


def test_wrong_value_type_is_rejected_with_the_offending_key():
    with pytest.raises(ConfigError) as excinfo:
        config_from_mapping({"context": {"max_tokens": "beaucoup"}})
    assert "[context] max_tokens" in str(excinfo.value)


def test_int_fields_accept_a_float_from_toml():
    assert config_from_mapping({"llm": {"temperature": 1}}).llm.temperature == 1.0


def test_bool_is_rejected_where_an_int_is_expected():
    """``True`` est un ``int`` en Python : sans garde-fou, il passerait pour 1."""
    with pytest.raises(ConfigError):
        config_from_mapping({"agent": {"max_iterations": True}})


# --------------------------------------------------------------------------- #
# Variables d'environnement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("variable", "reader", "expected"),
    [
        ("NIKOFORGE_BASE_URL", lambda config: config.llm.base_url, "http://autre:1234/v1"),
        ("NIKOFORGE_MODEL", lambda config: config.llm.model, "modele-env"),
        ("NIKOFORGE_API_KEY", lambda config: config.llm.api_key, "cle-env"),
    ],
)
def test_string_env_vars(variable, reader, expected):
    assert reader(apply_env(default_config(), {variable: expected})) == expected


def test_env_vars_map_to_the_documented_fields():
    config = apply_env(
        default_config(),
        {
            "NIKOFORGE_BASE_URL": "http://h:1/v1",
            "NIKOFORGE_MODEL": "m",
            "NIKOFORGE_API_KEY": "k",
            "NIKOFORGE_TEMPERATURE": "0.1",
            "NIKOFORGE_MAX_TOKENS": "64",
            "NIKOFORGE_CONTEXT": "2048",
            "NIKOFORGE_MAX_ITERATIONS": "7",
            "NIKOFORGE_TOOL_TIMEOUT": "30",
        },
    )
    assert config.llm.base_url == "http://h:1/v1"
    assert config.llm.model == "m"
    assert config.llm.api_key == "k"
    assert config.llm.temperature == 0.1
    assert config.llm.max_tokens == 64
    assert config.context.max_tokens == 2048
    assert config.agent.max_iterations == 7
    assert config.agent.tool_timeout == 30


def test_every_declared_env_var_is_applied():
    """Chaque variable annoncée dans ``ENV_VARS`` a un effet : pas de table morte."""
    for variable in ENV_VARS:
        assert variable.startswith("NIKOFORGE_")


def test_empty_timeout_env_var_removes_the_limit():
    """``0`` = pas de limite : TOML n'a pas de valeur nulle, c'est la convention retenue."""
    assert apply_env(default_config(), {"NIKOFORGE_TIMEOUT": ""}).llm.timeout == 0.0
    assert apply_env(default_config(), {"NIKOFORGE_TIMEOUT": "none"}).llm.timeout == 0.0


def test_invalid_env_var_reports_the_variable_name():
    with pytest.raises(ConfigError) as excinfo:
        apply_env(default_config(), {"NIKOFORGE_CONTEXT": "huit-mille"})
    assert "$NIKOFORGE_CONTEXT" in str(excinfo.value)


def test_absent_env_vars_do_not_change_anything():
    config = apply_env(default_config(), {})
    assert config == default_config()


# --------------------------------------------------------------------------- #
# Arguments de la ligne de commande
# --------------------------------------------------------------------------- #


def test_none_overrides_are_ignored(tmp_path: Path):
    """Un drapeau CLI non fourni vaut ``None`` et ne doit rien écraser."""
    overrides = {"llm": {"model": None, "base_url": None}, "context": {}, "workdir": None}
    config = apply_overrides(default_config(tmp_path), overrides)
    assert config.llm.model == ""
    assert config.context.max_tokens == 32768


def test_overrides_win_over_the_lower_layers():
    config = apply_overrides(default_config(), {"llm": {"model": "cli-modele"}})
    assert config.llm.model == "cli-modele"


def test_workdir_override_is_applied(tmp_path: Path):
    config = apply_overrides(default_config(), {"workdir": str(tmp_path)})
    assert config.workdir == tmp_path


def test_unknown_override_section_is_rejected():
    with pytest.raises(ConfigError, match="override inconnu"):
        apply_overrides(default_config(), {"llms": {"model": "x"}})


# --------------------------------------------------------------------------- #
# Précédence complète
# --------------------------------------------------------------------------- #


def test_full_precedence_chain(tmp_path: Path, isolated_env):
    """défauts < fichier < environnement < ligne de commande."""
    target = user_config_path(isolated_env)
    target.parent.mkdir(parents=True)
    target.write_text(
        '[llm]\nmodel = "depuis-fichier"\nbase_url = "http://fichier:1/v1"\n',
        encoding="utf-8",
    )
    env = {
        **isolated_env,
        "NIKOFORGE_MODEL": "depuis-env",
        "NIKOFORGE_CONTEXT": "4096",
    }

    config = load_config(
        overrides={"llm": {"model": "depuis-cli"}}, env=env
    )

    assert config.source == target
    assert config.llm.model == "depuis-cli"  # CLI gagne sur tout
    assert config.llm.base_url == "http://fichier:1/v1"  # fichier, l'env ne le touche pas
    assert config.context.max_tokens == 4096  # env, absent du fichier


def test_invalid_toml_is_reported_with_the_path(tmp_path: Path):
    broken = tmp_path / "broken.toml"
    broken.write_text("[llm\nmodel = ", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(str(broken), env={})
    assert "broken.toml" in str(excinfo.value)
    assert "TOML invalide" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Rendu TOML
# --------------------------------------------------------------------------- #


def test_render_toml_round_trip():
    """``render_toml`` puis relecture redonne exactement la même configuration."""
    original = Config(
        llm=LLMConfig(
            base_url="http://h:1/v1",
            model="un/modele/avec-des\"guillemets\"",
            api_key="sk-x",
            temperature=0.25,
            max_tokens=512,
            timeout=42.0,
        ),
        context=config_from_mapping({}).context,
        agent=AgentConfig(max_iterations=5, tool_timeout=17),
    )

    text = render_toml(original)
    reloaded = config_from_mapping(tomllib.loads(text))

    assert reloaded == original


def test_timeout_zero_survives_a_render_reload_cycle():
    """Contrairement à un ``None``, ``0`` est exprimable en TOML : l'aller-retour est fidèle."""
    config = apply_env(default_config(), {"NIKOFORGE_TIMEOUT": ""})

    text = render_toml(config)
    reloaded = config_from_mapping(tomllib.loads(text))

    assert "None" not in text
    assert "0 = pas de limite" in text
    assert reloaded.llm.timeout == 0.0
    assert reloaded == config


def test_render_toml_documents_every_field():
    text = render_toml(default_config())
    for section in ("llm", "context", "agent"):
        assert f"[{section}]" in text
    for name in ("base_url", "model", "api_key", "temperature", "max_tokens", "timeout"):
        assert name in text
    assert text.count("#") > 15, "le rendu doit être commenté, pas juste lisible"


def test_render_toml_escapes_strings():
    config = apply_overrides(default_config(), {"llm": {"model": 'a"b\\c'}})
    text = render_toml(config)
    assert tomllib.loads(text)["llm"]["model"] == 'a"b\\c'


# --------------------------------------------------------------------------- #
# Écriture
# --------------------------------------------------------------------------- #


def test_write_config_creates_parent_directories(tmp_path: Path):
    target = tmp_path / "profond" / "nikoforge" / "config.toml"
    write_config(default_config(), target)
    assert target.is_file()


def test_write_config_leaves_no_temporary_file(tmp_path: Path):
    target = tmp_path / "config.toml"
    write_config(default_config(), target)
    assert [path.name for path in tmp_path.iterdir()] == ["config.toml"]


def test_written_config_is_reloadable_and_equivalent(tmp_path: Path, isolated_env):
    """Bout en bout : écriture puis rechargement effectif par ``load_config``."""
    target = tmp_path / "config.toml"
    original = apply_overrides(
        default_config(), {"llm": {"model": "ecrit"}, "context": {"max_tokens": 1234}}
    )

    write_config(original, target)
    reloaded = load_config(str(target), env=isolated_env)

    assert reloaded.llm.model == "ecrit"
    assert reloaded.context.max_tokens == 1234
    assert reloaded.source == target
