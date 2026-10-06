import pytest
from pydantic import ValidationError

from gravai.minutes.custom_template import DEFAULT_TONE, FREE_FORM_KEY, MAX_SECTIONS, CustomSpec, build_custom_template
from gravai.minutes.docx_writer import write_minutes
from gravai.minutes.prompt_builder import build_system_prompt, output_schema, parse_response

RETRO_SECTIONS = [
    {"key": "bom", "title": "O que foi bom", "type": "bullets", "instructions": "Pontos positivos citados pelo time."},
    {
        "key": "ruim",
        "title": "O que foi ruim",
        "type": "bullets",
        "instructions": "Problemas citados.",
        "allow_empty": True,
    },
    {
        "key": "acoes",
        "title": "Ações",
        "type": "table",
        "instructions": "Tarefas com dono.",
        "id_prefix": "A",
        "columns": [
            {"key": "acao", "label": "Ação"},
            {"key": "quem", "label": "Quem"},
            {"key": "prazo", "label": "Prazo", "format": "DD/MM"},
            {"key": "status", "label": "Status", "values": ["Pendente", "Feito"], "default": "Pendente"},
        ],
    },
]


def test_free_instructions_become_one_paragraph_section_with_the_users_text():
    spec = CustomSpec(
        name="Ata de retrospectiva", tone="Informal.", instructions="Quero o que foi bom e o que foi ruim."
    )
    template = build_custom_template(spec)

    assert template.id == "custom"
    assert template.name == "Ata de retrospectiva"
    assert template.tone == "Informal."
    assert [s.key for s in template.sections] == [FREE_FORM_KEY]
    section = template.sections[0]
    assert section.type == "paragraph" and section.required and not section.allow_empty
    assert "Quero o que foi bom e o que foi ruim." in section.instructions
    # Header and footer come from the skeleton, so the docx always has project/date.
    assert [h.key for h in template.header] == ["projeto", "data", "horario"]
    assert "{projeto}" in template.footer


def test_declared_sections_keep_order_types_columns_and_defaults():
    template = build_custom_template(CustomSpec(sections=RETRO_SECTIONS))

    assert [s.key for s in template.sections] == ["bom", "ruim", "acoes"]
    assert template.name == "Ata personalizada" and template.tone == DEFAULT_TONE
    bom, ruim, acoes = template.sections
    # Custom sections are shown even when empty unless the client says otherwise.
    assert bom.allow_empty and ruim.allow_empty and acoes.allow_empty
    assert acoes.type == "table" and acoes.id_prefix == "A"
    assert [c.key for c in acoes.columns] == ["acao", "quem", "prazo", "status"]
    assert acoes.columns[3].values == ["Pendente", "Feito"] and acoes.columns[3].default == "Pendente"


def test_min_items_makes_the_section_mandatory():
    spec = CustomSpec(sections=[{**RETRO_SECTIONS[0], "min_items": 2}])
    section = build_custom_template(spec).sections[0]
    assert section.min_items == 2 and not section.allow_empty


def test_built_template_works_with_prompt_builder_and_docx(tmp_path):
    template = build_custom_template(CustomSpec(title="RETRO", sections=RETRO_SECTIONS))

    assert set(output_schema(template)) == {"bom", "ruim", "acoes"}
    system = build_system_prompt(template)
    assert "Pontos positivos citados pelo time." in system and "Pendente, Feito" in system

    minutes = parse_response(
        template, '{"bom": ["Entregamos no prazo"], "ruim": [], "acoes": [{"acao": "Revisar CI", "quem": "Ana"}]}'
    )
    assert minutes["acoes"][0] == {"id": "A1", "acao": "Revisar CI", "quem": "Ana", "prazo": "", "status": "Pendente"}

    write_minutes(
        template, {"projeto": "Sprint 12", "data": "01/10/2026"}, ["Ana"], minutes, str(tmp_path / "retro.docx")
    )
    assert (tmp_path / "retro.docx").stat().st_size > 0


@pytest.mark.parametrize(
    "spec, match",
    [
        ({}, "exactly one"),
        ({"instructions": "   "}, "exactly one"),
        ({"instructions": "x", "sections": RETRO_SECTIONS}, "exactly one"),
        ({"sections": []}, "between 1 and"),
        ({"sections": [{**RETRO_SECTIONS[0], "key": f"s{i}"} for i in range(MAX_SECTIONS + 1)]}, "between 1 and"),
        ({"sections": [RETRO_SECTIONS[0], RETRO_SECTIONS[0]]}, "duplicated section keys"),
        ({"sections": [{**RETRO_SECTIONS[0], "key": "O que foi bom"}]}, "snake_case"),
        ({"sections": [{**RETRO_SECTIONS[0], "key": "1bom"}]}, "snake_case"),
        ({"sections": [{"key": "t", "title": "T", "type": "table", "instructions": "x"}]}, "needs 'columns'"),
        ({"sections": [{"key": "r", "title": "R", "type": "record", "instructions": "x"}]}, "needs 'fields'"),
        ({"sections": [{**RETRO_SECTIONS[0], "columns": [{"key": "a", "label": "A"}]}]}, "must not have"),
        (
            {"sections": [{**RETRO_SECTIONS[2], "columns": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]}]},
            "duplicated column",
        ),
        ({"sections": [{**RETRO_SECTIONS[0], "type": "paragraph", "min_items": 1}]}, "only applies"),
        ({"sections": [{**RETRO_SECTIONS[0], "instructions": ""}]}, "at least 1 character"),
    ],
)
def test_invalid_specs_are_rejected(spec, match):
    with pytest.raises(ValidationError, match=match):
        CustomSpec(**spec)
