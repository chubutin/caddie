"""Unidades.

Garmin devuelve METROS en todos lados (`shots[].meters`,
`longestShotInMeters`, `distanceWalked`). Los metros son el canonico: es la
unidad de origen y guardarlos no pierde nada.

Al usuario SIEMPRE se le muestran YARDAS. La conversion pasa en la capa de
presentacion, nunca en el almacenamiento. Las columnas derivadas llevan
sufijo explicito (`_m` / `_yd`) para que no se mezclen.
"""

from __future__ import annotations

YARDS_PER_METER = 1.0936132983377078


def m_to_yd(meters: float | None) -> float | None:
    """Metros -> yardas."""
    return None if meters is None else meters * YARDS_PER_METER


def yd(meters: float | None, *, decimals: int = 0) -> str:
    """Formatear metros como yardas, listo para mostrar."""
    if meters is None:
        return "-"
    return f"{m_to_yd(meters):.{decimals}f} yd"
