"""Herramientas estadisticas para no leer de mas en muestras chicas."""

from __future__ import annotations

import math

# z para 95%
Z = 1.959963985


def wilson(successes: int, n: int, z: float = Z) -> tuple[float, float]:
    """Intervalo de Wilson para una proporcion, en porcentaje.

    Mejor que el intervalo normal cuando n es chico o la proporcion se va a
    los extremos — que es justo el caso de "hoyos par 4 de 425-450 yardas".
    Un tramo con n=12 y 25% de pares no dice lo mismo que uno con n=300.
    """
    if n == 0:
        return (0.0, 100.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (
        max(0.0, (centre - margin) / denom) * 100,
        min(1.0, (centre + margin) / denom) * 100,
    )


def with_ci(rows: list[dict], *, successes: str, n: str, prefix: str) -> list[dict]:
    """Agregar columnas <prefix>_lo / <prefix>_hi con el intervalo de Wilson."""
    for row in rows:
        k = int(row[successes] or 0)
        total = int(row[n] or 0)
        lo, hi = wilson(k, total)
        row[f"{prefix}_lo"] = round(lo, 1)
        row[f"{prefix}_hi"] = round(hi, 1)
        row[f"{prefix}_ci"] = round((hi - lo) / 2, 1)
    return rows
