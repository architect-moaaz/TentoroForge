"""A place, as a field type: `location` holds `{lat, lng}`, rounded to about
100 m when captured. Stored as jsonb; distances are computed by the app SDK
(`near`, `distanceKm`), and a page shows a distance, never coordinates."""
from __future__ import annotations

from typing import Any

#: The spellings a data model uses for a place.
LOCATION_TYPES = frozenset({"location", "geo", "geopoint", "geo_point", "coordinates", "latlng", "point"})

#: The TypeScript shape a location value has in the SDK.
LOCATION_TS = "{ lat: number; lng: number }"


def is_location_field(field: Any) -> bool:
    return isinstance(field, dict) and str(field.get("type") or "").strip().lower() in LOCATION_TYPES
