"""Pydantic schemas for data model endpoints."""

from pydantic import BaseModel


class SchemaChangeRequest(BaseModel):
    instruction: str


class SqlQueryRequest(BaseModel):
    sql: str


class SeedRequest(BaseModel):
    row_count: int = 10
    theme: str | None = None
