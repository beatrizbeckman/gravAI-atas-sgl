"""
Builds the "custom" minutes template from what the client sends in the request.

The fixed templates (dell, professores, daily) live as JSON files. The custom one
has the same structure but is assembled in memory from a CustomSpec: either free
instructions (one paragraph section the model organizes as it sees fit) or an
explicit list of sections. Everything downstream (prompt_builder, docx_writer)
receives a regular MinutesTemplate and does not know the difference.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field as PField, model_validator

from minutes.templates import Field, MinutesTemplate, Section, load_template

MAX_SECTIONS = 15
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_TONE = "Formal e objetivo, em terceira pessoa, frases curtas. Registrar fatos, decisões e responsáveis; não reproduzir a conversa."
FREE_FORM_KEY = "conteudo"
FREE_FORM_TITLE = "CONTEÚDO"


class CustomField(BaseModel):
    """A column of a table section or a field of a record section."""
    key: str
    label: str
    format: str | None = None
    values: list[str] | None = None
    default: str | None = None
    instructions: str | None = None

    @model_validator(mode="after")
    def check_key(self):
        _check_key(self.key, "column/field")
        return self


class CustomSection(BaseModel):
    key: str
    title: str
    type: Literal["paragraph", "bullets", "topics", "table", "record"]
    instructions: str = PField(min_length=1)
    # Custom sections default to "always shown, may be empty": the model must not invent content.
    allow_empty: bool = True
    min_items: int | None = PField(default=None, ge=1)
    id_prefix: str | None = None
    id_label: str = "ID"
    columns: list[CustomField] | None = None
    fields: list[CustomField] | None = None

    @model_validator(mode="after")
    def check_shape(self):
        _check_key(self.key, "section")
        if self.type == "table" and not self.columns:
            raise ValueError(f"section '{self.key}' is a table and needs 'columns'")
        if self.type == "record" and not self.fields:
            raise ValueError(f"section '{self.key}' is a record and needs 'fields'")
        if self.type not in ("table", "record") and (self.columns or self.fields):
            raise ValueError(f"section '{self.key}' is a {self.type} and must not have 'columns' or 'fields'")
        for group in (self.columns, self.fields):
            keys = [f.key for f in group or []]
            duplicated = sorted({k for k in keys if keys.count(k) > 1})
            if duplicated:
                raise ValueError(f"section '{self.key}' has duplicated column/field keys: {duplicated}")
        if self.min_items and self.type not in ("bullets", "topics", "table"):
            raise ValueError(f"section '{self.key}': 'min_items' only applies to bullets, topics and table")
        return self


class CustomSpec(BaseModel):
    """
    The `custom` object of the request (contract section 3.4). Exactly one of
    `instructions` (free form) or `sections` (declared structure) must be given.
    """
    name: str | None = None
    title: str | None = None
    subtitle: str | None = None
    tone: str | None = None
    instructions: str | None = None
    sections: list[CustomSection] | None = None

    @model_validator(mode="after")
    def check_one_form(self):
        has_instructions = bool(self.instructions and self.instructions.strip())
        has_sections = self.sections is not None
        if has_instructions == has_sections:
            raise ValueError("custom template needs exactly one of 'instructions' or 'sections'")
        if has_sections:
            if not 1 <= len(self.sections) <= MAX_SECTIONS:
                raise ValueError(f"custom template needs between 1 and {MAX_SECTIONS} sections, got {len(self.sections)}")
            keys = [s.key for s in self.sections]
            duplicated = sorted({k for k in keys if keys.count(k) > 1})
            if duplicated:
                raise ValueError(f"duplicated section keys: {duplicated}")
        return self


def _check_key(key: str, what: str) -> None:
    if not KEY_PATTERN.match(key):
        raise ValueError(f"{what} key '{key}' must be snake_case: lowercase letters, digits and '_', starting with a letter")


def build_custom_template(spec: CustomSpec) -> MinutesTemplate:
    """
    Returns a MinutesTemplate for this request. The skeleton (header fields,
    footer, language, logo) comes from templates/custom.json; name, title, tone
    and sections come from the spec.
    """
    base = load_template("custom")
    if spec.sections is not None:
        sections = [_to_section(s) for s in spec.sections]
    else:
        sections = [
            Section(
                key=FREE_FORM_KEY,
                title=FREE_FORM_TITLE,
                type="paragraph",
                required=True,
                allow_empty=False,
                instructions=(
                    "Instruções de quem pediu a ata, a seguir. Organize o texto como for mais claro, "
                    "em parágrafos ou tópicos, cobrindo tudo o que foi pedido e nada além do que está na transcrição.\n"
                    + spec.instructions.strip()
                ),
            )
        ]

    return base.model_copy(
        update={
            "name": (spec.name or base.name).strip(),
            "title": (spec.title or base.title).strip(),
            "subtitle": (spec.subtitle or "").strip(),
            "tone": (spec.tone or DEFAULT_TONE).strip(),
            "sections": sections,
        }
    )


def _to_section(s: CustomSection) -> Section:
    return Section(
        key=s.key,
        title=s.title.strip(),
        type=s.type,
        instructions=s.instructions.strip(),
        required=True,
        allow_empty=s.allow_empty and not s.min_items,
        min_items=s.min_items,
        id_prefix=s.id_prefix,
        id_label=s.id_label,
        columns=[Field(**c.model_dump()) for c in s.columns] if s.columns else None,
        fields=[Field(**f.model_dump()) for f in s.fields] if s.fields else None,
    )
