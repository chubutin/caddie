"""Geometria y coordenadas.

OJO: Garmin usa DOS escalas distintas, a veces en la misma respuesta.

- `courseSnapshots.lat/lon`        -> grados * 1e6
- tiros (`startLoc`/`endLoc`) y
  `pinPosition`                    -> semicirculos (grados * 2**31/180)

Confundirlas pone los tiros a cientos de km del campo.
"""

from __future__ import annotations

import math
from typing import Any

SEMICIRCLE_TO_DEGREES = 180.0 / 2**31
COURSE_COORD_SCALE = 1e6
EARTH_RADIUS_M = 6_371_000.0

Point = tuple[float, float]  # (lat, lon) en grados


def from_semicircles(node: dict[str, Any] | None) -> Point | None:
    """Convertir un {'lat': int, 'lon': int} en semicirculos a grados."""
    if not node or node.get("lat") is None or node.get("lon") is None:
        return None
    return (node["lat"] * SEMICIRCLE_TO_DEGREES, node["lon"] * SEMICIRCLE_TO_DEGREES)


def from_course_scale(node: dict[str, Any] | None) -> Point | None:
    """Convertir el lat/lon de un courseSnapshot (grados * 1e6) a grados."""
    if not node or node.get("lat") is None or node.get("lon") is None:
        return None
    return (node["lat"] / COURSE_COORD_SCALE, node["lon"] / COURSE_COORD_SCALE)


def haversine_m(a: Point, b: Point) -> float:
    """Distancia en metros entre dos puntos (lat, lon) en grados."""
    lat1, lon1 = a
    lat2, lon2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))
