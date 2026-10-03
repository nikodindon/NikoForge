"""``nikoforge.protocol`` : (dé)codage des appels d'outils et validation des arguments.

Ce module remplace le parser par expression régulière de la v2 (bug C1 et ses trois
sous-défauts). Il est pur — aucun réseau — donc testable exhaustivement, y compris sur les
contenus qui cassaient la v2.

Le test le plus important est ``test_round_trip_sur_contenus_pieges`` : tout ce que
l'encodeur produit doit être relu à l'identique, quelle que soit la valeur.
"""

from __future__ import annotations

import json
import types

import pytest

from nikoforge.protocol import (
    CDATA_CLOSE,
    CDATA_OPEN,
    SPECS_BY_NAME,
    TOOL_SPECS,
    Parameter,
    ParsedResponse,
    ProtocolError,
    TextParse,
    ToolArgumentsError,
    ToolCall,
    ToolSpec,
    encode_text_call,
    encode_text_calls,
    encode_value,
    openai_tools,
    parse_native_calls,
    parse_response,
    parse_text_calls,
    prepare_call,
    render_tools_for_prompt,
    validate_arguments,
)


def block(name: str, **params: str) -> str:
    """Construit un bloc d'appel comme l'écrirait un modèle."""
    inner = "".join(f'<param name="{key}">{value}</param>' for key, value in params.items())
    return f'<tool_calls><tool name="{name}">{inner}</tool></tool_calls>'


# --------------------------------------------------------------------------- #
# Spécification des outils
# --------------------------------------------------------------------------- #


def test_the_five_tools_are_declared_once():
    assert sorted(SPECS_BY_NAME) == ["bash", "edit_file", "list_files", "read_file", "write_file"]


def test_names_and_required_are_derived_from_the_parameters():
    spec = SPECS_BY_NAME["bash"]
    assert spec.names == ("command", "timeout")
    assert spec.required == ("command",)


def test_parameter_lookup():
    assert SPECS_BY_NAME["read_file"].parameter("path").type == "string"
    assert SPECS_BY_NAME["read_file"].parameter("absent") is None


def test_render_prompt_lists_the_signature_and_the_description():
    rendered = SPECS_BY_NAME["edit_file"].render_prompt()
    assert rendered.startswith("- edit_file(path, old_content, new_content) → ")
    assert "unique" in rendered


def test_render_tools_for_prompt_covers_every_tool():
    text = render_tools_for_prompt()
    for spec in TOOL_SPECS:
        assert spec.name in text


def test_openai_schema_shape():
    schema = SPECS_BY_NAME["bash"].to_openai_schema()
    assert schema["type"] == "function"
    function = schema["function"]
    assert function["name"] == "bash"
    assert function["parameters"]["required"] == ["command"]
    assert function["parameters"]["properties"]["timeout"]["type"] == "integer"


def test_openai_tools_returns_all_specs():
    assert len(openai_tools()) == len(TOOL_SPECS)


# --------------------------------------------------------------------------- #
# Décodage : cas nominaux
# --------------------------------------------------------------------------- #


def test_single_call_single_parameter():
    parsed = parse_text_calls(block("read_file", path="a.py"))
    assert parsed.calls == (ToolCall("read_file", {"path": "a.py"}),)
    assert parsed.text == ""
    assert parsed.incomplete is False


def test_several_parameters():
    parsed = parse_text_calls(block("write_file", path="a.py", content="x = 1"))
    assert parsed.calls[0].arguments == {"path": "a.py", "content": "x = 1"}


def test_several_tools_in_one_block():
    text = (
        '<tool_calls><tool name="list_files"><param name="path">.</param></tool>'
        '<tool name="bash"><param name="command">pytest</param></tool></tool_calls>'
    )
    assert [call.name for call in parse_text_calls(text).calls] == ["list_files", "bash"]


def test_several_blocks():
    text = block("list_files", path=".") + "\n" + block("read_file", path="a.py")
    assert [call.name for call in parse_text_calls(text).calls] == ["list_files", "read_file"]


def test_tool_without_parameters():
    parsed = parse_text_calls('<tool_calls><tool name="list_files"></tool></tool_calls>')
    assert parsed.calls == (ToolCall("list_files", {}),)


def test_surrounding_prose_is_kept_but_markup_removed():
    text = "Je regarde.\n" + block("list_files", path=".") + "\nVoilà."
    parsed = parse_text_calls(text)
    assert parsed.text == "Je regarde.\n\nVoilà."
    assert "<tool_calls" not in parsed.text
    assert len(parsed.calls) == 1


def test_text_without_any_call_is_returned_as_is():
    parsed = parse_text_calls("Juste une réponse.")
    assert parsed == TextParse(text="Juste une réponse.", calls=(), incomplete=False)


def test_multiline_value_keeps_inner_newlines():
    parsed = parse_text_calls(block("write_file", path="a.txt", content="l1\nl2\nl3"))
    assert parsed.calls[0].arguments["content"] == "l1\nl2\nl3"


def test_empty_parameter_value_is_preserved_not_dropped():
    """Supprimer du texte doit être possible : une chaîne vide est une valeur, pas une absence."""
    parsed = parse_text_calls(
        '<tool_calls><tool name="edit_file">'
        '<param name="path">a.txt</param>'
        '<param name="old_content">ligne</param>'
        '<param name="new_content"></param>'
        "</tool></tool_calls>"
    )
    assert parsed.calls[0].arguments["new_content"] == ""


def test_single_quoted_attributes_are_accepted():
    """La v2 exigeait des guillemets doubles et ignorait le reste, sans rien dire."""
    text = "<tool_calls><tool name='read_file'><param name='path'>a.py</param></tool></tool_calls>"
    assert parse_text_calls(text).calls == (ToolCall("read_file", {"path": "a.py"}),)


# --------------------------------------------------------------------------- #
# Décodage : robustesse
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "<toolbox><tool name=\"read_file\"><param name=\"path\">a</param></tool></toolbox>",
        "<parameter>du bruit</parameter>",
        "<params><param name=\"x\">1</param></params>",
        "<tools><tool name=\"read_file\"></tool></tools>",
        "un texte qui parle de <tool et </tool> sans balise englobante",
    ],
)
def test_lookalike_tags_are_not_executed(text):
    """Aucun contenu ne doit être exécuté s'il n'est pas dans un vrai bloc ``<tool_calls>``."""
    parsed = parse_text_calls(text)
    assert parsed.calls == ()
    assert parsed.incomplete is False


def test_tool_tag_outside_a_tool_calls_block_is_ignored():
    text = '<tool name="bash"><param name="command">rm -rf /</param></tool>'
    assert parse_text_calls(text).calls == ()


def test_unterminated_block_is_reported_not_guessed():
    """Réponse coupée par max_tokens : on le signale, on ne devine pas."""
    text = "Je vais écrire.\n<tool_calls><tool name=\"write_file\"><param name=\"path\">a</param>"
    parsed = parse_text_calls(text)
    assert parsed.incomplete is True
    assert parsed.calls == ()
    assert "Je vais écrire." in parsed.text
    assert "<tool_calls" in parsed.text  # conservé : le modèle doit voir sa propre coupure


def test_attribute_without_quotes_is_ignored():
    assert parse_text_calls('<tool_calls><tool name=read_file></tool></tool_calls>').calls == ()


def test_call_without_a_name_is_skipped():
    assert parse_text_calls('<tool_calls><tool><param name="path">a</param></tool></tool_calls>').calls == ()


# --------------------------------------------------------------------------- #
# Les trois sous-défauts de C1 : comportement INVERSÉ par rapport à la v2
# --------------------------------------------------------------------------- #


def test_leading_indentation_is_preserved():
    """Bug C1b : la v2 faisait ``.strip()`` sur tous les paramètres.

    Un modèle qui indente correctement produisait un fichier Python qui ne compilait pas.
    """
    text = (
        '<tool_calls><tool name="write_file"><param name="path">code.py</param>'
        '<param name="content">    indentation = True\n    return indentation\n</param>'
        "</tool></tool_calls>"
    )
    content = parse_text_calls(text).calls[0].arguments["content"]
    assert content == "    indentation = True\n    return indentation"


def test_inner_trailing_whitespace_is_preserved():
    text = block("write_file", path="a.txt", content="ligne1   \nligne2\t\nfin")
    assert parse_text_calls(text).calls[0].arguments["content"] == "ligne1   \nligne2\t\nfin"


def test_xml_entities_are_decoded():
    """Bug C1c : la v2 laissait ``&lt;div&gt;`` littéral dans le fichier écrit."""
    text = block("write_file", path="x.html", content="&lt;div&gt;&amp;nbsp;&lt;/div&gt;")
    assert parse_text_calls(text).calls[0].arguments["content"] == "<div>&nbsp;</div>"


def test_entities_are_decoded_in_a_single_pass():
    """``&amp;lt;`` doit donner ``&lt;``, pas ``<`` (sinon double décodage)."""
    text = block("write_file", path="x", content="&amp;lt;")
    assert parse_text_calls(text).calls[0].arguments["content"] == "&lt;"


# --------------------------------------------------------------------------- #
# CDATA
# --------------------------------------------------------------------------- #


def test_cdata_value_is_taken_raw():
    text = block("write_file", path="a", content=f"{CDATA_OPEN}<div>&nbsp;</div>{CDATA_CLOSE}")
    assert parse_text_calls(text).calls[0].arguments["content"] == "<div>&nbsp;</div>"


def test_cdata_is_not_normalised():
    """Dans un CDATA, aucun saut de ligne de bord n'est retiré : c'est du contenu brut."""
    text = block("write_file", path="a", content=f"{CDATA_OPEN}\n  x  \n{CDATA_CLOSE}")
    assert parse_text_calls(text).calls[0].arguments["content"] == "\n  x  \n"


@pytest.mark.parametrize(
    "content",
    [
        "avant </param> après",
        "avant </tool> après",
        "avant </tool_calls> après",
        "<tool_calls><tool name=\"bash\"><param name=\"command\">ls</param></tool></tool_calls>",
        "fin du fichier. </param></tool></tool_calls>",
        "</tool_calls>\n</tool>\n</param>",
    ],
)
def test_cdata_protects_every_ambiguous_sequence(content):
    """C'est ce qui supprime la classe de bugs C1a : dans un CDATA, rien n'est interprété."""
    text = block("write_file", path="d.md", content=f"{CDATA_OPEN}{content}{CDATA_CLOSE}")
    parsed = parse_text_calls(text)
    assert parsed.calls[0].arguments["content"] == content


def test_content_containing_the_cdata_terminator_falls_back_to_entities():
    """Un CDATA ne peut pas contenir ``]]>`` : l'encodeur replie alors sur les entités.

    C'est le seul contenu pour lequel le CDATA est impossible, et il reste fidèle — le
    décodeur rétablit les entités à l'identique.
    """
    content = "emboîté <![CDATA[ imbriqué ]]> suite"
    call = ToolCall("write_file", {"path": "a", "content": content})

    encoded = encode_text_call(call)

    assert "&lt;![CDATA[" in encoded
    assert parse_text_calls(encoded).calls[0].arguments["content"] == content


def test_truncated_cdata_yields_no_call():
    """Une CDATA non terminée signifie une réponse coupée : on n'exécute rien.

    Écrire un fichier dont on ne possède que le début serait pire que ne rien faire : le
    fichier serait créé, tronqué, et l'outil répondrait « succès ».
    """
    text = (
        '<tool_calls><tool name="write_file"><param name="path">a</param>'
        f'<param name="content">{CDATA_OPEN}du texte'
    )
    parsed = parse_text_calls(text)

    assert parsed.calls == ()
    assert parsed.incomplete is True
    assert "<tool_calls" in parsed.text


# --------------------------------------------------------------------------- #
# Encodage
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["simple", "avec des espaces", "x=1;y=2", "a/b.txt"])
def test_plain_values_are_not_wrapped(value):
    assert encode_value(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "print('a < b')",
        "a & b",
        "ligne1\nligne2",
        "  indenté",
        "fini  ",
        "texte avec ]]> dedans",
        "<tool_calls>",
    ],
)
def test_ambiguous_values_are_escaped_or_wrapped(value):
    encoded = encode_value(value)
    assert encoded != value
    assert encoded.startswith(CDATA_OPEN) or "&" in encoded


def test_non_string_values_are_serialised_as_json():
    assert encode_value(5) == "5"
    assert encode_value({"a": 1}) == '{"a": 1}'


def test_encode_text_call_shape():
    rendered = encode_text_call(ToolCall("read_file", {"path": "a.py"}))
    assert rendered.startswith("<tool_calls>\n<tool name=\"read_file\">\n")
    assert '<param name="path">a.py</param>' in rendered
    assert rendered.endswith("</tool>\n</tool_calls>")


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("write_file", {"path": "a", "content": "print('a < b')"}),
        ("write_file", {"path": "a", "content": "avant </param> après"}),
        ("write_file", {"path": "a", "content": "avant </tool> après"}),
        ("write_file", {"path": "a", "content": "avant </tool_calls> après"}),
        ("write_file", {"path": "a", "content": "<![CDATA[ imbriqué ]]> suite"}),
        ("write_file", {"path": "a", "content": "    indentation = True\n    return x\n"}),
        ("write_file", {"path": "a", "content": "ligne1   \nligne2\t"}),
        ("write_file", {"path": "a", "content": "unicode éàçü ★ 中文 🎉"}),
        ("write_file", {"path": "a", "content": "CRLF\r\nligne2\r\n"}),
        ("write_file", {"path": "a", "content": ""}),
        ("write_file", {"path": "a", "content": "a" * 100_000}),
        ("write_file", {"path": "a", "content": "texte terminé par ]]> ici"}),
        ("edit_file", {"path": "avec des espaces/dans le nom.txt", "old_content": "x", "new_content": ""}),
        ("bash", {"command": "echo '</tool>' && ls", "timeout": 5}),
        ("bash", {"command": "printf 'a\\\\nb\\n'"}),
        ("list_files", {"path": "."}),
        ("list_files", {}),
    ],
)
def test_round_trip_on_adversarial_payloads(name, arguments):
    """Tout ce que l'encodeur produit doit être relu à l'identique.

    C'est la propriété qui garantit qu'aucun contenu de fichier ne peut casser le décodage —
    la v2 échouait dès la première occurrence de ``</tool>`` dans le contenu.
    """
    call = ToolCall(name, arguments)

    decoded = parse_text_calls(encode_text_calls([call]))

    assert len(decoded.calls) == 1, decoded
    assert decoded.calls[0].name == name
    for key, value in arguments.items():
        expected = value if isinstance(value, str) else str(value)
        assert decoded.calls[0].arguments[key] == expected, f"perte sur {key}"


def test_round_trip_of_several_calls_with_commands():
    calls = [
        ToolCall("bash", {"command": "echo '</tool>'"}, call_id="c1"),
        ToolCall("write_file", {"path": "a", "content": "<x>"}),
    ]
    decoded = parse_text_calls(encode_text_calls(calls))
    assert [call.name for call in decoded.calls] == ["bash", "write_file"]
    assert decoded.calls[0].arguments["command"] == "echo '</tool>'"


# --------------------------------------------------------------------------- #
# Forme native
# --------------------------------------------------------------------------- #


def test_native_calls_from_a_dict():
    raw = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "list_files", "arguments": '{"path": "."}'},
        }
    ]
    assert parse_native_calls(raw) == (
        ToolCall("list_files", {"path": "."}, call_id="call_1"),
    )


def test_native_calls_from_sdk_objects():
    raw = [
        types.SimpleNamespace(
            id="call_2",
            function=types.SimpleNamespace(name="bash", arguments='{"command": "ls"}'),
        )
    ]
    assert parse_native_calls(raw) == (ToolCall("bash", {"command": "ls"}, call_id="call_2"),)


def test_native_call_with_empty_arguments():
    raw = [{"id": "c", "function": {"name": "list_files", "arguments": ""}}]
    assert parse_native_calls(raw) == (ToolCall("list_files", {}, call_id="c"),)


def test_native_call_without_arguments_key():
    assert parse_native_calls([{"id": "c", "function": {"name": "x"}}])[0].arguments == {}


def test_native_call_with_already_decoded_arguments():
    raw = [{"id": "c", "function": {"name": "x", "arguments": {"path": "a"}}}]
    assert parse_native_calls(raw)[0].arguments == {"path": "a"}


def test_native_absent_or_empty():
    assert parse_native_calls(None) == ()
    assert parse_native_calls([]) == ()


def test_native_invalid_json_raises():
    raw = [{"id": "c", "function": {"name": "x", "arguments": "{pas du json"}}]
    with pytest.raises(ProtocolError) as excinfo:
        parse_native_calls(raw)
    assert "arguments illisibles" in str(excinfo.value)
    assert "x" in str(excinfo.value)


def test_native_non_object_json_raises():
    raw = [{"id": "c", "function": {"name": "x", "arguments": "[1, 2]"}}]
    with pytest.raises(ProtocolError, match="objet JSON attendu"):
        parse_native_calls(raw)


def test_native_call_without_a_name_raises():
    with pytest.raises(ProtocolError, match="sans nom"):
        parse_native_calls([{"id": "c", "function": {}}])


# --------------------------------------------------------------------------- #
# parse_response
# --------------------------------------------------------------------------- #


def test_response_prefers_native_calls():
    native = [{"id": "c", "function": {"name": "bash", "arguments": '{"command":"ls"}'}}]
    parsed = parse_response("je liste", native)
    assert parsed.calls == (ToolCall("bash", {"command": "ls"}, call_id="c"),)
    assert parsed.text == "je liste"


def test_response_falls_back_to_text_calls():
    parsed = parse_response("je liste\n" + block("bash", command="ls"))
    assert parsed.calls == (ToolCall("bash", {"command": "ls"}),)
    assert parsed.text == "je liste"


def test_response_strips_text_markup_even_when_native_calls_exist():
    """Un serveur peut mélanger les deux formes : on ne garde pas le balisage dans l'historique."""
    native = [{"id": "c", "function": {"name": "bash", "arguments": "{}"}}]
    parsed = parse_response("dit\n" + block("read_file", path="a"), native)
    assert "<tool_calls" not in parsed.text
    assert [call.name for call in parsed.calls] == ["bash"]


def test_response_keeps_reasoning_separate():
    parsed = parse_response("réponse", reasoning="réflexion interne")
    assert parsed.reasoning == "réflexion interne"
    assert "réflexion" not in parsed.text


def test_response_handles_none_content():
    parsed = parse_response(None)
    assert parsed == ParsedResponse()


def test_response_reports_truncation():
    parsed = parse_response("début\n<tool_calls><tool name=\"read_file\">")
    assert parsed.incomplete is True


# --------------------------------------------------------------------------- #
# Validation des arguments
# --------------------------------------------------------------------------- #


def test_valid_arguments_pass_through_untouched():
    resolved = validate_arguments(SPECS_BY_NAME["read_file"], {"path": "a b.txt"})
    assert resolved == {"path": "a b.txt"}


def test_empty_string_is_a_valid_value():
    """Bug C16 inversé : ``new_content=""`` doit être accepté pour supprimer du texte."""
    resolved = validate_arguments(
        SPECS_BY_NAME["edit_file"],
        {"path": "a.txt", "old_content": "ligne\n", "new_content": ""},
    )
    assert resolved["new_content"] == ""


def test_missing_required_parameter_is_reported():
    with pytest.raises(ToolArgumentsError, match="manquant"):
        validate_arguments(SPECS_BY_NAME["read_file"], {})


def test_none_for_a_required_parameter_is_reported_as_missing():
    with pytest.raises(ToolArgumentsError, match="manquant"):
        validate_arguments(SPECS_BY_NAME["read_file"], {"path": None})


def test_unknown_parameter_lists_the_valid_ones():
    """Remplace l'alias ``raw`` accepté en silence par la v2 (bug C15a)."""
    with pytest.raises(ToolArgumentsError) as excinfo:
        validate_arguments(SPECS_BY_NAME["read_file"], {"raw": "a.txt"})
    message = str(excinfo.value)
    assert "raw" in message
    assert "path" in message


def test_optional_parameter_absent_is_not_injected():
    resolved = validate_arguments(SPECS_BY_NAME["bash"], {"command": "ls"})
    assert resolved == {"command": "ls"}


def test_integer_parameter_accepts_a_string():
    resolved = validate_arguments(SPECS_BY_NAME["bash"], {"command": "ls", "timeout": "5"})
    assert resolved["timeout"] == 5


def test_integer_parameter_rejects_a_bool():
    """``True`` est un ``int`` en Python : sans garde-fou il passerait pour 1."""
    with pytest.raises(ToolArgumentsError, match="booléen"):
        validate_arguments(SPECS_BY_NAME["bash"], {"command": "ls", "timeout": True})


def test_integer_parameter_rejects_text():
    with pytest.raises(ToolArgumentsError, match="entier attendu"):
        validate_arguments(SPECS_BY_NAME["bash"], {"command": "ls", "timeout": "beaucoup"})


def test_string_parameter_accepts_a_number():
    resolved = validate_arguments(SPECS_BY_NAME["write_file"], {"path": "a", "content": 42})
    assert resolved["content"] == "42"


def test_string_parameter_rejects_a_list():
    with pytest.raises(ToolArgumentsError, match="chaîne attendue"):
        validate_arguments(SPECS_BY_NAME["write_file"], {"path": "a", "content": ["x"]})


def test_validation_error_names_the_tool_and_the_parameter():
    with pytest.raises(ToolArgumentsError) as excinfo:
        validate_arguments(SPECS_BY_NAME["bash"], {"command": "ls", "timeout": "x"})
    assert "bash.timeout" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# prepare_call
# --------------------------------------------------------------------------- #


def test_prepare_call_validates_and_keeps_the_call_id():
    prepared = prepare_call(ToolCall("bash", {"command": "ls", "timeout": "3"}, call_id="c7"))
    assert prepared == ToolCall("bash", {"command": "ls", "timeout": 3}, call_id="c7")


def test_prepare_call_rejects_an_unknown_tool_and_lists_the_available_ones():
    with pytest.raises(ToolArgumentsError) as excinfo:
        prepare_call(ToolCall("ftp_upload", {}))
    message = str(excinfo.value)
    assert "ftp_upload" in message
    assert "read_file" in message


def test_prepare_call_uses_a_custom_registry():
    spec = ToolSpec("ping", "Ping un hôte", (Parameter("host", "string", "Hôte"),))
    prepared = prepare_call(ToolCall("ping", {"host": "localhost"}), {"ping": spec})
    assert prepared.arguments == {"host": "localhost"}


def test_prepare_call_rejects_a_parameter_of_the_custom_schema():
    spec = ToolSpec("ping", "Ping un hôte", (Parameter("host", "string", "Hôte"),))
    with pytest.raises(ToolArgumentsError, match="inconnu"):
        prepare_call(ToolCall("ping", {"cible": "localhost"}), {"ping": spec})


def test_schema_is_json_serialisable():
    """Le schéma part tel quel dans la requête HTTP."""
    assert json.loads(json.dumps(openai_tools()))[3]["function"]["name"] == "edit_file"
