import pytest

from gravai.minutes.templates import available_templates, load_template


def test_every_template_file_is_valid():
    assert available_templates() == ["custom", "daily", "dell", "professores"]
    for template_id in available_templates():
        template = load_template(template_id)
        assert template.id == template_id
        assert template.sections


def test_fixed_templates_keep_the_document_order():
    dell = [s.title for s in load_template("dell").sections]
    assert dell[:2] == ["RESUMO EM TÓPICOS", "TÓPICOS DISCUTIDOS"]
    assert dell[-3:] == ["DECISÕES", "PLANO DE AÇÃO", "PRÓXIMA REUNIÃO"]

    daily = load_template("daily")
    assert [s.title for s in daily.sections][-1] == "Combinados"
    assert daily.sections[0].key == "resumo_topicos"
    assert {s.group for s in daily.sections[1:-1]} == {"Como foi"}


def test_fixed_templates_open_with_an_optional_bullet_summary():
    # Suggested in the evaluation form: a short part with topics only, to read at a glance.
    for template_id in ("dell", "professores", "daily"):
        first = load_template(template_id).sections[0]
        assert (first.key, first.type, first.required, first.synthesis) == ("resumo_topicos", "bullets", False, True)
        assert "sem texto corrido" in first.instructions


def test_dell_and_professores_differ_only_where_the_pdfs_do():
    dell, prof = load_template("dell"), load_template("professores")
    assert [s.key for s in dell.sections if s.key != "ideias_propostas"] == [
        s.key for s in prof.sections if s.key != "feedback_professores"
    ]
    assert [h.key for h in prof.header] == [h.key for h in dell.header]


def test_unknown_template_lists_the_available_ones():
    with pytest.raises(FileNotFoundError, match="dell"):
        load_template("nao-existe")
