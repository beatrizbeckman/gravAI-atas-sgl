import json
import os
from typing import Literal

from pydantic import BaseModel, model_validator

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


class Field(BaseModel):
    key: str
    label: str
    format: str | None = None
    values: list[str] | None = None
    default: str | None = None
    instructions: str | None = None


class HeaderField(Field):
    source: Literal["request", "transcript"] = "request"
    required: bool = False


class Participants(BaseModel):
    title: str
    label: str | None = None
    source: Literal["request", "transcript"] = "transcript"
    inline: bool = False


class Section(BaseModel):
    key: str
    title: str
    type: Literal["paragraph", "bullets", "topics", "table", "record"]
    instructions: str
    group: str | None = None
    required: bool = True
    allow_empty: bool = False
    min_items: int | None = None
    id_prefix: str | None = None
    columns: list[Field] | None = None
    fields: list[Field] | None = None

    @model_validator(mode="after")
    def check_type_fields(self):
        if self.type == "table" and not self.columns:
            raise ValueError(f"section '{self.key}' is a table without columns")
        if self.type == "record" and not self.fields:
            raise ValueError(f"section '{self.key}' is a record without fields")
        return self


class MinutesTemplate(BaseModel):
    id: str
    name: str
    title: str
    subtitle: str = ""
    logo: str | None = None
    footer: str
    language: str = "pt-BR"
    tone: str
    header: list[HeaderField]
    participants: Participants
    sections: list[Section]

    @model_validator(mode="after")
    def check_unique_keys(self):
        keys = [s.key for s in self.sections]
        duplicated = {k for k in keys if keys.count(k) > 1}
        if duplicated:
            raise ValueError(f"duplicated section keys in template '{self.id}': {sorted(duplicated)}")
        return self


def available_templates() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(TEMPLATES_DIR) if f.endswith(".json"))


def load_template(template_id: str) -> MinutesTemplate:
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Unknown template '{template_id}'. Available: {', '.join(available_templates())}")
    with open(path, "r", encoding="utf-8") as f:
        return MinutesTemplate.model_validate(json.load(f))
