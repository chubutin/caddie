"""Largo del hoyo, derivado de los tiros.

Garmin no expone el yardaje: no viene en la scorecard y no hay endpoint de
canchas (37 rutas probadas, todas 404 — ver `endpoints.py`). Lo unico que
trae `courseSnapshots.tees` es handicap por hoyo, rating y slope.

Asi que lo medimos con los tiros propios. Dos medidas por ronda-hoyo:

- `straight_m`  : tee -> pin en linea recta. Subestima los doglegs.
- `corridor_m`  : tee -> donde cayo el drive -> pin. Sigue la curva del hoyo,
                  pero incluye tu propio error de direccion.

La diferencia entre ambas detecta doglegs, **calibrando contra los par 3**:
ahi las dos medidas deberian coincidir, asi que lo que sobra es el piso de
ruido de tu dispersion. Lo que supere ese piso es curva real del hoyo.

Importante: esto mide el camino que JUGASTE, no la linea del arquitecto. Para
correlacionar score con distancia es la variable correcta (es la distancia que
efectivamente enfrentaste, con el tee y la bandera de ese dia). Para comparar
contra la tarjeta del club, no lo es.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .geo import from_semicircles, haversine_m

# Un tee->pin fuera de este rango es basura (GPS perdido, hoyo mal asignado).
MIN_PLAUSIBLE_M = 50.0
MAX_PLAUSIBLE_M = 700.0
# Un corredor mas largo que esto respecto de la recta no es un dogleg: es un
# drive perdido en otra calle.
MAX_CORRIDOR_RATIO = 2.2

TEE_LIE = "TeeBox"


@dataclass(frozen=True)
class HoleMeasurement:
    round_id: int
    course_id: int | None
    hole_number: int
    par: int | None
    straight_m: float
    corridor_m: float | None

    @property
    def dogleg_excess_m(self) -> float | None:
        if self.corridor_m is None:
            return None
        return self.corridor_m - self.straight_m


def measure_round(
    round_id: int,
    course_id: int | None,
    hole_pars: str,
    hole_shots: Iterable[dict[str, Any]],
) -> list[HoleMeasurement]:
    """Medir cada hoyo de una ronda a partir de su shot data."""
    out: list[HoleMeasurement] = []
    for entry in hole_shots:
        number = entry.get("holeNumber")
        pin = from_semicircles(entry.get("pinPosition"))
        if number is None or pin is None:
            continue

        shots = entry.get("shots") or []
        tee_shot = next(
            (s for s in shots if (s.get("startLoc") or {}).get("lie") == TEE_LIE), None
        )
        if tee_shot is None:
            continue
        tee = from_semicircles(tee_shot.get("startLoc"))
        if tee is None:
            continue

        straight = haversine_m(tee, pin)
        if not MIN_PLAUSIBLE_M < straight < MAX_PLAUSIBLE_M:
            continue

        corridor = None
        landing = from_semicircles(tee_shot.get("endLoc"))
        if landing is not None:
            candidate = haversine_m(tee, landing) + haversine_m(landing, pin)
            if candidate < straight * MAX_CORRIDOR_RATIO:
                corridor = candidate

        # Par ciclico: en canchas de 9 jugadas dos veces, el hoyo 10 es el 1.
        par = (
            int(hole_pars[(number - 1) % len(hole_pars)]) if hole_pars else None
        )
        out.append(
            HoleMeasurement(round_id, course_id, number, par, straight, corridor)
        )
    return out


@dataclass(frozen=True)
class HoleProfile:
    """Resumen de un hoyo a lo largo de todas las rondas jugadas ahi."""

    course_id: int | None
    hole_number: int
    par: int | None
    n: int
    straight_median_m: float
    straight_p10_m: float
    straight_p90_m: float
    corridor_median_m: float | None
    dogleg_excess_m: float | None


def _pct(values: list[float], q: float) -> float:
    return values[min(len(values) - 1, int(q * len(values)))]


def build_profiles(
    measurements: Iterable[HoleMeasurement], *, min_rounds: int = 3
) -> list[HoleProfile]:
    """Agregar las mediciones por (cancha, hoyo)."""
    grouped: dict[tuple[int | None, int], list[HoleMeasurement]] = defaultdict(list)
    for m in measurements:
        grouped[(m.course_id, m.hole_number)].append(m)

    profiles: list[HoleProfile] = []
    for (course_id, hole), items in sorted(
        grouped.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1])
    ):
        if len(items) < min_rounds:
            continue
        straights = sorted(m.straight_m for m in items)
        corridors = sorted(m.corridor_m for m in items if m.corridor_m is not None)
        pars = [m.par for m in items if m.par is not None]
        corridor_median = st.median(corridors) if corridors else None
        straight_median = st.median(straights)
        profiles.append(
            HoleProfile(
                course_id=course_id,
                hole_number=hole,
                par=st.mode(pars) if pars else None,
                n=len(items),
                straight_median_m=straight_median,
                straight_p10_m=_pct(straights, 0.10),
                straight_p90_m=_pct(straights, 0.90),
                corridor_median_m=corridor_median,
                dogleg_excess_m=(
                    corridor_median - straight_median if corridor_median else None
                ),
            )
        )
    return profiles


def noise_floor_m(profiles: Iterable[HoleProfile]) -> float | None:
    """Piso de ruido: el exceso tipico en par 3, donde no puede haber dogleg.

    En un par 3 el corredor pasa por donde cayo tu tee shot, asi que el exceso
    sobre la recta es puro error tuyo. Ese es el umbral contra el que hay que
    medir los par 4 y 5.
    """
    excesses = [
        p.dogleg_excess_m
        for p in profiles
        if p.par == 3 and p.dogleg_excess_m is not None
    ]
    return st.median(excesses) if excesses else None
