"""Schemas for the visual editor endpoints."""

from typing import Literal
from pydantic import BaseModel


class TailwindEdit(BaseModel):
    file: str
    line: int
    action: Literal["add", "remove", "replace"]
    class_name: str
    replace_with: str | None = None


class TextEdit(BaseModel):
    file: str
    line: int
    old_text: str
    new_text: str


class PropEdit(BaseModel):
    file: str
    line: int
    prop_name: str
    old_value: str
    new_value: str


class VisualEditRequest(BaseModel):
    tailwind_edits: list[TailwindEdit] = []
    text_edits: list[TextEdit] = []
    prop_edits: list[PropEdit] = []


class AIEditRequest(BaseModel):
    instruction: str
    file: str | None = None
    line: int | None = None
    context_element: str | None = None


class AddSectionRequest(BaseModel):
    route: str
    template_id: str | None = None
    custom_prompt: str | None = None
    insert_position: str = "end"  # "end", "start", or "after:{xpath}"


class ReorderSectionRequest(BaseModel):
    route: str
    source_file: str
    source_line: int
    target_file: str
    target_line: int
    position: Literal["before", "after"]
