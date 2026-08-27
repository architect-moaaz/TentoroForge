from dataclasses import dataclass
from typing import Any


@dataclass
class FieldHint:
    name: str
    type: str
    nullable: bool = False
    primary_key: bool = False


@dataclass
class FixtureBundle:
    """A set of fake records keyed by entity name."""
    records: dict[str, list[dict[str, Any]]]
