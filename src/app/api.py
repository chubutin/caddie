"""Capa 3: API de lectura sobre Postgres.

Convencion de unidades: la base guarda METROS; esta capa expone YARDAS.
Todo campo de distancia que sale por la API termina en `_yd`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import session
from .db import connect
from .stats import with_ci
from .units import YARDS_PER_METER

logger = logging.getLogger(__name__)

app = FastAPI(title="Caddie Virtual", version="0.1.0")
# Solo el front local. No "*": con POST de login en juego, un origen abierto
# dejaria que cualquier pagina dispare un login desde tu browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{os.getenv('WEB_PORT', '5173')}",
        f"http://127.0.0.1:{os.getenv('WEB_PORT', '5173')}",
    ],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

# Factor como literal SQL, para convertir en la query y no fila por fila.
YD = f"* {YARDS_PER_METER}"


def q(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def q1(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = q(sql, params)
    return rows[0] if rows else None


@app.get("/api/health")
def health() -> dict[str, Any]:
    row = q1("SELECT count(*) AS rounds FROM rounds")
    return {"ok": True, "rounds": row["rounds"] if row else 0}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return q1(
        """
        SELECT count(*)                                   AS rounds,
               min(started_at)::date                      AS first_round,
               max(started_at)::date                      AS last_round,
               count(*) FILTER (WHERE is_complete
                                AND holes_completed = 18) AS full_rounds,
               (SELECT count(*) FROM shots)               AS shots,
               (SELECT count(*) FROM courses)             AS courses,
               round(avg(strokes) FILTER (WHERE is_complete
                                          AND holes_completed = 18), 1) AS avg_18,
               min(strokes) FILTER (WHERE is_complete
                                    AND holes_completed = 18)           AS best_18
        FROM rounds
        """
    ) or {}


@app.get("/api/rounds")
def rounds(limit: int = Query(50, le=500), offset: int = 0) -> list[dict[str, Any]]:
    return q(
        f"""
        SELECT r.id, r.started_at, r.strokes, r.par, r.score_vs_par,
               r.holes_completed, r.round_type, r.is_complete, r.has_shot_data,
               c.name AS course, c.course_global_id,
               s.putts, s.greens_in_regulation, s.greens_recorded,
               s.fairways_hit, s.fairways_recorded,
               round((r.distance_walked_m {YD})::numeric, 0) AS walked_yd
        FROM rounds r
        LEFT JOIN courses c USING (course_global_id)
        LEFT JOIN round_stats s ON s.round_id = r.id AND s.segment = 'round'
        ORDER BY r.started_at DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


@app.get("/api/rounds/{round_id}")
def round_detail(round_id: int) -> dict[str, Any]:
    head = q1(
        """
        SELECT r.*, c.name AS course
        FROM rounds r LEFT JOIN courses c USING (course_global_id)
        WHERE r.id = %s
        """,
        (round_id,),
    )
    if head is None:
        raise HTTPException(404, "ronda no encontrada")
    head.pop("course_name_raw", None)
    holes = q(
        f"""
        SELECT hole_number, par, hole_handicap, strokes, putts, penalties,
               fairway_outcome, score_vs_par,
               round((straight_m {YD})::numeric, 0) AS length_yd,
               round((corridor_m {YD})::numeric, 0) AS corridor_yd
        FROM holes WHERE round_id = %s ORDER BY hole_number
        """,
        (round_id,),
    )
    shots = q(
        f"""
        SELECT s.hole_number, s.shot_order, s.shot_type, s.start_lie, s.end_lie,
               round((s.meters {YD})::numeric, 0) AS distance_yd,
               ST_Y(s.start_loc::geometry) AS start_lat,
               ST_X(s.start_loc::geometry) AS start_lon,
               ST_Y(s.end_loc::geometry)   AS end_lat,
               ST_X(s.end_loc::geometry)   AS end_lon,
               c.model, c.name AS club_name
        FROM shots s LEFT JOIN clubs c ON c.id = s.club_id
        WHERE s.round_id = %s
        ORDER BY s.hole_number, s.shot_order
        """,
        (round_id,),
    )
    return {"round": head, "holes": holes, "shots": shots}


@app.get("/api/clubs")
def clubs(solo_bolsa_actual: bool = False) -> list[dict[str, Any]]:
    """Distancias por palo. Dos fuentes: la que calcula Garmin y la nuestra.

    La nuestra sale de los tiros con palo asignado; `shots_measured` dice
    cuantos son. El clubId falta en buena parte de los tiros, asi que las dos
    columnas no tienen por que coincidir.

    Los palos retirados se incluyen por defecto: sus tiros son historia real y
    sacarlos falsearia los promedios de las temporadas en que los jugaste.
    `solo_bolsa_actual=true` deja unicamente los que siguen en la bolsa.
    """
    where = "WHERE NOT c.retired AND NOT c.deleted" if solo_bolsa_actual else ""
    return q(
        f"""
        SELECT c.id, c.label, c.slot, c.model, c.name, c.club_type_id,
               c.shaft_length, c.retired, c.deleted, c.shots_count,
               round((c.avg_distance_m  {YD})::numeric, 0) AS garmin_avg_yd,
               round((c.max_recent_m    {YD})::numeric, 0) AS max_recent_yd,
               round((c.max_lifetime_m  {YD})::numeric, 0) AS max_lifetime_yd,
               c.pct_fairway_hit, c.pct_green_hit,
               c.pct_green_miss_short, c.pct_green_miss_long,
               c.pct_green_miss_left, c.pct_green_miss_right,
               m.shots_measured,
               round((m.median_m {YD})::numeric, 0) AS median_yd,
               round((m.p25_m    {YD})::numeric, 0) AS p25_yd,
               round((m.p75_m    {YD})::numeric, 0) AS p75_yd
        FROM clubs c
        LEFT JOIN (
            SELECT club_id,
                   count(*) AS shots_measured,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY meters) AS median_m,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY meters) AS p25_m,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY meters) AS p75_m
            FROM shots
            WHERE club_id IS NOT NULL AND shot_type <> 'PUTT'
              AND NOT exclude_from_stats AND meters > 0
            GROUP BY club_id
        ) m ON m.club_id = c.id
        {where}
        -- Los que jugas hoy primero y en orden de bolsa (driver -> putter).
        -- Ordenar por distancia mandaba los palos nuevos al fondo, justo los
        -- que hay que nombrar: todavia no tienen un solo tiro medido.
        ORDER BY c.retired, c.club_type_id
        """
    )


@app.get("/api/scoring/by-par")
def scoring_by_par() -> list[dict[str, Any]]:
    return q(
        f"""
        SELECT h.par,
               count(*)                                  AS holes,
               round(avg(h.strokes), 2)                  AS avg_strokes,
               round(avg(h.score_vs_par), 2)             AS avg_vs_par,
               round(avg(h.putts), 2)                    AS avg_putts,
               round(avg((h.straight_m {YD}))::numeric, 0) AS avg_length_yd,
               round(100.0 * count(*) FILTER (WHERE h.score_vs_par <= 0) / count(*), 1) AS pct_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE h.score_vs_par = 1) / count(*), 1)  AS pct_bogey,
               round(100.0 * count(*) FILTER (WHERE h.score_vs_par >= 2) / count(*), 1) AS pct_doble_o_peor
        FROM holes h JOIN rounds r ON r.id = h.round_id
        WHERE h.par IS NOT NULL AND h.strokes IS NOT NULL AND NOT r.exclude_from_stats
        GROUP BY h.par ORDER BY h.par
        """
    )


@app.get("/api/scoring/by-distance")
def scoring_by_distance(bucket_yd: int = Query(25, ge=10, le=100)) -> list[dict[str, Any]]:
    """Score promedio por par y por tramo de yardaje.

    Contesta: a partir de que largo se te empieza a ir el hoyo.
    """
    return q(
        f"""
        WITH h AS (
            SELECT hh.par, hh.score_vs_par, hh.strokes,
                   floor((hh.straight_m {YD}) / %s)::int AS b
            FROM holes hh JOIN rounds r ON r.id = hh.round_id
            WHERE hh.par IS NOT NULL AND hh.strokes IS NOT NULL
              AND hh.straight_m IS NOT NULL AND NOT r.exclude_from_stats
        )
        SELECT par,
               b * %s             AS from_yd,
               b * %s + %s        AS to_yd,
               count(*)           AS holes,
               round(avg(score_vs_par), 2) AS avg_vs_par,
               round(avg(strokes), 2)      AS avg_strokes
        FROM h
        GROUP BY par, b
        HAVING count(*) >= 10
        ORDER BY par, from_yd
        """,
        (bucket_yd, bucket_yd, bucket_yd, bucket_yd),
    )


@app.get("/api/trend")
def trend(window: int = Query(10, ge=3, le=50)) -> list[dict[str, Any]]:
    """Serie de score de rondas 18 completas, con media movil."""
    return q(
        """
        SELECT started_at::date AS date, strokes, par, score_vs_par,
               round(avg(score_vs_par) OVER (ORDER BY started_at
                     ROWS BETWEEN %s PRECEDING AND CURRENT ROW), 2) AS rolling_vs_par
        FROM rounds
        WHERE is_complete AND holes_completed = 18 AND score_type = 'STROKE_PLAY'
          AND NOT exclude_from_stats
        ORDER BY started_at
        """,
        (window - 1,),
    )


@app.get("/api/courses")
def courses() -> list[dict[str, Any]]:
    return q(
        f"""
        SELECT c.course_global_id, c.name, c.city, c.round_par,
               count(r.id) AS rounds,
               round(avg(r.strokes) FILTER (WHERE r.is_complete
                                            AND r.holes_completed = 18), 1) AS avg_18,
               round((SELECT sum(straight_median_m) {YD}
                      FROM hole_profiles p
                      WHERE p.course_global_id = c.course_global_id)::numeric, 0) AS length_yd
        FROM courses c LEFT JOIN rounds r USING (course_global_id)
        GROUP BY c.course_global_id, c.name, c.city, c.round_par
        ORDER BY rounds DESC
        """
    )


@app.get("/api/courses/{course_id}/holes")
def course_holes(course_id: int) -> list[dict[str, Any]]:
    return q(
        f"""
        SELECT p.hole_number, p.par, p.n_rounds, p.shape,
               round((p.straight_median_m {YD})::numeric, 0) AS length_yd,
               round((p.straight_p10_m    {YD})::numeric, 0) AS p10_yd,
               round((p.straight_p90_m    {YD})::numeric, 0) AS p90_yd,
               round((p.dogleg_excess_m   {YD})::numeric, 0) AS dogleg_excess_yd,
               a.avg_strokes, a.avg_vs_par, a.holes_played
        FROM hole_profiles p
        LEFT JOIN (
            SELECT h.hole_number,
                   round(avg(h.strokes), 2) AS avg_strokes,
                   round(avg(h.score_vs_par), 2) AS avg_vs_par,
                   count(*) AS holes_played
            FROM holes h JOIN rounds r ON r.id = h.round_id
            WHERE r.course_global_id = %s AND h.strokes IS NOT NULL
            GROUP BY h.hole_number
        ) a USING (hole_number)
        WHERE p.course_global_id = %s
        ORDER BY p.hole_number
        """,
        (course_id, course_id),
    )


@app.get("/api/dispersion")
def dispersion(club_id: int | None = None, min_shots: int = 20) -> list[dict[str, Any]]:
    """Dispersion por palo: distancia y resultado del tiro."""
    return q(
        f"""
        SELECT s.club_id, c.label, c.model, c.name AS club_name,
               count(*) AS shots,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY s.meters) {YD})::numeric, 0) AS median_yd,
               round((percentile_cont(0.1) WITHIN GROUP (ORDER BY s.meters) {YD})::numeric, 0) AS p10_yd,
               round((percentile_cont(0.9) WITHIN GROUP (ORDER BY s.meters) {YD})::numeric, 0) AS p90_yd,
               round(100.0 * count(*) FILTER (WHERE s.end_lie = 'Fairway') / count(*), 1) AS pct_fairway,
               round(100.0 * count(*) FILTER (WHERE s.end_lie = 'Green')   / count(*), 1) AS pct_green,
               round(100.0 * count(*) FILTER (WHERE s.end_lie = 'Rough')   / count(*), 1) AS pct_rough,
               round(100.0 * count(*) FILTER (WHERE s.end_lie = 'Bunker')  / count(*), 1) AS pct_bunker
        FROM shots s JOIN clubs c ON c.id = s.club_id
        WHERE s.club_id IS NOT NULL AND s.shot_type <> 'PUTT'
          AND NOT s.exclude_from_stats AND s.meters > 0
          AND (%s::bigint IS NULL OR s.club_id = %s)
        GROUP BY s.club_id, c.label, c.model, c.name
        HAVING count(*) >= %s
        ORDER BY median_yd DESC
        """,
        (club_id, club_id, min_shots),
    )


@app.get("/api/data-quality")
def data_quality() -> list[dict[str, Any]]:
    """Cobertura de AutoShot y de clubId por año. Importa para leer el resto."""
    return q(
        """
        WITH s AS (
            SELECT extract(year FROM r.started_at)::int AS year,
                   count(*) FILTER (WHERE sh.shot_type <> 'PUTT')          AS shots_non_putt,
                   count(*) FILTER (WHERE sh.shot_type =  'PUTT')          AS shots_putt,
                   count(*) FILTER (WHERE sh.shot_source = 'SENSOR')       AS shots_sensor,
                   count(*)                                                AS shots_total,
                   count(*) FILTER (WHERE sh.shot_type <> 'PUTT'
                                      AND sh.club_id IS NOT NULL)          AS with_club
            FROM shots sh JOIN rounds r ON r.id = sh.round_id
            GROUP BY 1
        ), h AS (
            SELECT extract(year FROM r.started_at)::int AS year,
                   count(DISTINCT r.id)       AS rounds,
                   sum(hh.strokes)            AS strokes,
                   sum(hh.putts)              AS putts
            FROM rounds r JOIN holes hh ON hh.round_id = r.id
            GROUP BY 1
        )
        SELECT h.year, h.rounds, h.strokes, h.putts,
               (h.strokes - h.putts)                                   AS non_putt_strokes,
               s.shots_non_putt, s.shots_putt,
               round(100.0 * s.shots_non_putt
                     / nullif(h.strokes - h.putts, 0), 0)              AS pct_capture,
               round(100.0 * s.with_club
                     / nullif(s.shots_non_putt, 0), 0)                 AS pct_with_club,
               round(100.0 * s.shots_sensor
                     / nullif(s.shots_total, 0), 0)                    AS pct_sensor
        FROM h JOIN s USING (year)
        ORDER BY h.year
        """
    )


# ---------------------------------------------------------------- dispersion
# Desvio lateral firmado respecto de la linea al centro del green:
#   lateral = distancia * sin(rumbo_del_tiro - rumbo_al_green)
#
# OJO: el `pinPosition` de Garmin NO es la bandera del dia — es un punto fijo
# del green que trae el mapa de la cancha. Para una linea de juego eso esta
# BIEN (al green se le apunta al centro), pero inhabilita cualquier metrica de
# proximity al pin.
# Positivo = derecha, negativo = izquierda. ST_Azimuth anda sobre geography.
#
# Para los TEE shots la linea al pin solo sirve como linea de juego si el hoyo
# es recto: en un dogleg apuntas al codo, no al green. Por eso se filtra
# contra hole_profiles.shape, que se deriva comparando el corredor real contra
# la recta (calibrado en par 3). Para los APPROACH el centro del green SI es el objetivo.

LATERAL_SQL = """
    ST_Distance(s.start_loc, s.end_loc)
      * sin(ST_Azimuth(s.start_loc, s.end_loc) - ST_Azimuth(s.start_loc, h.green_ref))
"""


@app.get("/api/dispersion/lateral")
def dispersion_lateral(
    shot_type: str = Query("TEE", pattern="^(TEE|APPROACH)$"),
    min_shots: int = 25,
) -> list[dict[str, Any]]:
    """Dispersion izquierda/derecha por palo, en yardas.

    `bias_yd` es la mediana: si da positivo tiras a la derecha de forma
    sistematica. `spread_yd` (p90 - p10) es cuanto te abris.
    """
    straight_only = "AND (p.shape IS NULL OR p.shape = 'recto')" if shot_type == "TEE" else ""
    return q(
        f"""
        WITH lat AS (
            SELECT s.club_id, ({LATERAL_SQL}) AS lateral_m
            FROM shots s
            JOIN holes h  ON h.round_id = s.round_id AND h.hole_number = s.hole_number
            JOIN rounds r ON r.id = s.round_id
            LEFT JOIN hole_profiles p
                   ON p.course_global_id = r.course_global_id
                  AND p.hole_number = s.hole_number
            WHERE s.shot_type = %s
              AND s.club_id IS NOT NULL
              AND h.green_ref IS NOT NULL
              AND s.start_loc IS NOT NULL AND s.end_loc IS NOT NULL
              AND s.meters > 30
              AND NOT s.exclude_from_stats
              {straight_only}
        )
        SELECT lat.club_id, c.label, c.slot, c.model, c.name AS club_name, c.retired,
               count(*) AS shots,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY lateral_m) {YD})::numeric, 1) AS bias_yd,
               round((percentile_cont(0.1) WITHIN GROUP (ORDER BY lateral_m) {YD})::numeric, 0) AS p10_yd,
               round((percentile_cont(0.9) WITHIN GROUP (ORDER BY lateral_m) {YD})::numeric, 0) AS p90_yd,
               round(((percentile_cont(0.9) WITHIN GROUP (ORDER BY lateral_m)
                     - percentile_cont(0.1) WITHIN GROUP (ORDER BY lateral_m)) {YD})::numeric, 0) AS spread_yd,
               round(100.0 * count(*) FILTER (WHERE lateral_m < -5) / count(*), 0) AS pct_izq,
               round(100.0 * count(*) FILTER (WHERE lateral_m BETWEEN -5 AND 5) / count(*), 0) AS pct_centro,
               round(100.0 * count(*) FILTER (WHERE lateral_m > 5) / count(*), 0) AS pct_der
        FROM lat JOIN clubs c ON c.id = lat.club_id
        GROUP BY lat.club_id, c.label, c.slot, c.model, c.name, c.retired
        HAVING count(*) >= %s
        ORDER BY count(*) DESC
        """,
        (shot_type, min_shots),
    )


@app.get("/api/dispersion/shots")
def dispersion_shots(club_id: int, shot_type: str = "TEE", limit: int = 600) -> list[dict[str, Any]]:
    """Nube de puntos de un palo: avance vs desvio lateral, en yardas.

    Es el scatter que alimenta la elipse de dispersion.
    """
    return q(
        f"""
        SELECT round((({LATERAL_SQL}) {YD})::numeric, 1) AS lateral_yd,
               round((ST_Distance(s.start_loc, s.end_loc)
                      * cos(ST_Azimuth(s.start_loc, s.end_loc)
                            - ST_Azimuth(s.start_loc, h.green_ref)) {YD})::numeric, 1) AS carry_yd,
               s.end_lie
        FROM shots s
        JOIN holes h ON h.round_id = s.round_id AND h.hole_number = s.hole_number
        WHERE s.club_id = %s AND s.shot_type = %s
          AND h.green_ref IS NOT NULL AND s.start_loc IS NOT NULL AND s.end_loc IS NOT NULL
          AND s.meters > 30 AND NOT s.exclude_from_stats
        LIMIT %s
        """,
        (club_id, shot_type, limit),
    )


# Proximity NO existe a proposito: medirla requiere la posicion real de la
# bandera, y el `pinPosition` de Garmin es un punto fijo del green (toma 2-4
# valores en 79 rondas del mismo hoyo). "Distancia al centro del green" no es
# proximity y presentarla como tal seria mentir.


@app.get("/api/putting")
def putting() -> list[dict[str, Any]]:
    """Putts por hoyo, segun la tarjeta.

    NO hay metricas de distancia de putt, a proposito. Los putts con GPS solo
    existen 2022-2025 (hacian falta sensores de palo) y cuando se los mide, el
    porcentaje de embocados sale plano en ~50-58% desde 0 hasta 20 yd. Eso es
    imposible — desde 2 yd se emboca ~90% y desde 18 yd ~5% — asi que la
    posicion de la bola en el green no tiene la precision necesaria. Se probo
    con el pinPosition registrado y deduciendo la posicion del hoyo del ultimo
    putt: misma curva plana en los dos casos.

    Lo que SI es confiable es `holes.putts`, que viene de la tarjeta.

    GIR se deriva con la definicion estandar: (golpes - putts) <= par - 2.
    """
    return q(
        """
        WITH h AS (
            SELECT hh.par, hh.putts, hh.strokes,
                   (hh.strokes - hh.putts) <= (hh.par - 2) AS gir
            FROM holes hh JOIN rounds r ON r.id = hh.round_id
            WHERE hh.par IS NOT NULL AND hh.putts IS NOT NULL
              AND hh.strokes IS NOT NULL AND NOT r.exclude_from_stats
        )
        SELECT par,
               count(*)                                              AS holes,
               round(avg(putts), 2)                                  AS avg_putts,
               round(100.0 * count(*) FILTER (WHERE putts = 1) / count(*), 1) AS pct_1_putt,
               round(100.0 * count(*) FILTER (WHERE putts = 2) / count(*), 1) AS pct_2_putts,
               round(100.0 * count(*) FILTER (WHERE putts >= 3) / count(*), 1) AS pct_3_o_mas,
               round(100.0 * count(*) FILTER (WHERE gir) / count(*), 1)        AS pct_gir,
               round(avg(putts) FILTER (WHERE gir), 2)               AS putts_con_gir,
               round(avg(putts) FILTER (WHERE NOT gir), 2)           AS putts_sin_gir
        FROM h
        GROUP BY par ORDER BY par
        """
    )


@app.get("/api/putting/trend")
def putting_trend() -> list[dict[str, Any]]:
    """Putts por vuelta de 18, en el tiempo, con media movil de 10.

    Excluye las 17 vueltas donde no se anotaron putts (vienen como 0).
    """
    return q(
        """
        SELECT r.started_at::date AS date, s.putts,
               s.greens_in_regulation, s.greens_recorded,
               round(avg(s.putts) OVER (ORDER BY r.started_at
                     ROWS BETWEEN 9 PRECEDING AND CURRENT ROW), 2) AS rolling_putts
        FROM rounds r JOIN round_stats s ON s.round_id = r.id AND s.segment = 'round'
        WHERE r.is_complete AND r.holes_completed = 18
          AND NOT r.exclude_from_stats
          -- 17 vueltas tienen putts = 0 y ningun hoyo con putts cargados:
          -- esos dias no los anotaste. No son vueltas sin putts.
          AND s.putts > 0
        ORDER BY r.started_at
        """
    )


# =========================================================== analisis de juego
# La pregunta no es "cuanto hago en promedio" sino "donde tengo chances y que
# puedo cambiar". Todo lo de aca viene con n y con intervalo de confianza:
# un tramo con 12 hoyos no dice lo mismo que uno con 300.
#
# GIR se deriva con la definicion estandar: (golpes - putts) <= par - 2.

HOLE_BASE = f"""
    SELECT hh.par, hh.strokes, hh.putts, hh.penalties, hh.fairway_outcome,
           hh.score_vs_par, hh.hole_handicap,
           (hh.straight_m {YD}) AS yd,
           (hh.strokes - hh.putts) <= (hh.par - 2) AS gir,
           r.course_global_id, r.started_at
    FROM holes hh JOIN rounds r ON r.id = hh.round_id
    WHERE hh.par IS NOT NULL AND hh.strokes IS NOT NULL
      AND NOT r.exclude_from_stats
"""


@app.get("/api/analysis/outcomes")
def analysis_outcomes(
    par: int = Query(4, ge=3, le=5),
    bucket_yd: int = Query(25, ge=10, le=100),
    min_n: int = Query(15, ge=5),
) -> list[dict[str, Any]]:
    """Probabilidad de cada resultado segun el largo del hoyo.

    Contesta directo: en un par 4 de 400+ yardas, cuanta chance real tengo de
    hacer par, comparado con uno de 350.
    """
    rows = q(
        f"""
        WITH h0 AS ({HOLE_BASE} AND hh.straight_m IS NOT NULL AND hh.par = %s),
             h AS (SELECT *, floor(yd / %s)::int AS b FROM h0)
        SELECT b * %s      AS from_yd,
               b * %s + %s AS to_yd,
               count(*)                                            AS n,
               count(*) FILTER (WHERE score_vs_par <= 0)            AS n_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE score_vs_par <= 0) / count(*), 1) AS pct_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE score_vs_par = 1) / count(*), 1)  AS pct_bogey,
               round(100.0 * count(*) FILTER (WHERE score_vs_par >= 2) / count(*), 1) AS pct_doble_o_peor,
               round(avg(strokes), 2)                               AS avg_strokes,
               round(avg(score_vs_par), 2)                          AS avg_vs_par,
               round(100.0 * count(*) FILTER (WHERE gir) / count(*), 1)              AS pct_gir,
               round(100.0 * count(*) FILTER (WHERE fairway_outcome = 'HIT')
                     / nullif(count(*) FILTER (WHERE fairway_outcome IS NOT NULL), 0), 1) AS pct_fairway,
               round(avg(putts), 2)                                 AS avg_putts,
               round(100.0 * count(*) FILTER (WHERE putts >= 3) / count(*), 1)       AS pct_3_putts,
               round(avg(penalties), 2)                             AS avg_penalties
        FROM h
        GROUP BY b
        HAVING count(*) >= %s
        ORDER BY from_yd
        """,
        (par, bucket_yd, bucket_yd, bucket_yd, bucket_yd, min_n),
    )
    return with_ci(rows, successes="n_par_o_mejor", n="n", prefix="par_o_mejor")


@app.get("/api/analysis/fairway")
def analysis_fairway(
    par: int = Query(4, ge=4, le=5),
    bucket_yd: int = Query(50, ge=25, le=100),
    min_n: int = Query(12, ge=5),
) -> list[dict[str, Any]]:
    """Cuanto cambia el resultado haber pegado la calle, segun el largo.

    Es la palanca de estrategia: si en los hoyos largos pegar la calle casi no
    mueve la aguja, conviene darle; si la mueve mucho, conviene asegurar.
    """
    rows = q(
        f"""
        WITH h0 AS (
            {HOLE_BASE} AND hh.straight_m IS NOT NULL AND hh.par = %s
                        AND hh.fairway_outcome IS NOT NULL
        ), h AS (SELECT *, floor(yd / %s)::int AS b FROM h0)
        SELECT b * %s      AS from_yd,
               b * %s + %s AS to_yd,
               CASE WHEN fairway_outcome = 'HIT' THEN 'calle' ELSE 'fuera' END AS resultado_salida,
               count(*)                                              AS n,
               count(*) FILTER (WHERE score_vs_par <= 0)              AS n_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE score_vs_par <= 0) / count(*), 1) AS pct_par_o_mejor,
               round(avg(score_vs_par), 2)                            AS avg_vs_par,
               round(100.0 * count(*) FILTER (WHERE gir) / count(*), 1) AS pct_gir
        FROM h
        GROUP BY b, 3
        HAVING count(*) >= %s
        ORDER BY from_yd, resultado_salida
        """,
        (par, bucket_yd, bucket_yd, bucket_yd, bucket_yd, min_n),
    )
    return with_ci(rows, successes="n_par_o_mejor", n="n", prefix="par_o_mejor")


@app.get("/api/analysis/tee-club")
def analysis_tee_club(
    par: int = Query(4, ge=3, le=5),
    min_n: int = Query(20, ge=5),
) -> list[dict[str, Any]]:
    """Que pasa segun con que palo salis, en hoyos del mismo par.

    Solo tiros de salida con palo identificado. Ojo: no es un experimento —
    elegis el palo segun el hoyo, asi que hay seleccion. Sirve para mirar, no
    para concluir causalidad.
    """
    rows = q(
        f"""
        WITH t AS (
            SELECT s.club_id, hh.score_vs_par, hh.strokes, hh.par,
                   hh.fairway_outcome,
                   (hh.strokes - hh.putts) <= (hh.par - 2) AS gir,
                   (hh.straight_m {YD}) AS hole_yd,
                   (s.meters {YD}) AS tee_yd
            FROM shots s
            JOIN holes hh ON hh.round_id = s.round_id AND hh.hole_number = s.hole_number
            JOIN rounds r ON r.id = s.round_id
            WHERE s.shot_type = 'TEE' AND s.club_id IS NOT NULL
              AND hh.par = %s AND hh.strokes IS NOT NULL AND hh.putts IS NOT NULL
              AND NOT r.exclude_from_stats AND NOT s.exclude_from_stats
        )
        SELECT t.club_id, c.label, c.slot, c.model, c.name AS club_name, c.retired,
               count(*)                                   AS n,
               count(*) FILTER (WHERE score_vs_par <= 0)   AS n_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE score_vs_par <= 0) / count(*), 1) AS pct_par_o_mejor,
               round(avg(score_vs_par), 2)                 AS avg_vs_par,
               round(avg(hole_yd))                         AS avg_hole_yd,
               round(avg(tee_yd))                          AS avg_tee_yd,
               round(100.0 * count(*) FILTER (WHERE fairway_outcome = 'HIT')
                     / nullif(count(*) FILTER (WHERE fairway_outcome IS NOT NULL), 0), 1) AS pct_fairway,
               round(100.0 * count(*) FILTER (WHERE gir) / count(*), 1) AS pct_gir
        FROM t JOIN clubs c ON c.id = t.club_id
        GROUP BY t.club_id, c.label, c.slot, c.model, c.name, c.retired
        HAVING count(*) >= %s
        ORDER BY avg_hole_yd DESC
        """,
        (par, min_n),
    )
    return with_ci(rows, successes="n_par_o_mejor", n="n", prefix="par_o_mejor")


@app.get("/api/analysis/leaks")
def analysis_leaks() -> list[dict[str, Any]]:
    """Donde se te van los golpes, en total y por hoyo.

    Ordenado por golpes perdidos TOTALES sobre el par, que es lo que mueve el
    score final: un segmento donde perdes poco por hoyo pero jugas muchisimo
    pesa mas que uno catastrofico y raro.
    """
    return q(
        f"""
        WITH h AS ({HOLE_BASE}),
        seg AS (
            SELECT 'Par ' || par ||
                   CASE WHEN yd IS NULL THEN ' (sin largo)'
                        WHEN par = 3 AND yd >= 175 THEN ' largo (175+ yd)'
                        WHEN par = 3 THEN ' corto (<175 yd)'
                        WHEN par = 4 AND yd >= 375 THEN ' largo (375+ yd)'
                        WHEN par = 4 AND yd >= 300 THEN ' medio (300-375 yd)'
                        WHEN par = 4 THEN ' corto (<300 yd)'
                        WHEN par = 5 AND yd >= 475 THEN ' largo (475+ yd)'
                        WHEN par = 5 THEN ' corto (<475 yd)'
                   END AS segmento,
                   score_vs_par, putts, penalties, gir, par
            FROM h
        )
        SELECT segmento,
               count(*)                                   AS hoyos,
               sum(score_vs_par)                          AS golpes_perdidos,
               round(avg(score_vs_par), 2)                AS por_hoyo,
               round(100.0 * count(*) FILTER (WHERE score_vs_par <= 0) / count(*), 1) AS pct_par_o_mejor,
               round(100.0 * count(*) FILTER (WHERE score_vs_par >= 2) / count(*), 1) AS pct_doble_o_peor,
               round(100.0 * count(*) FILTER (WHERE gir) / count(*), 1)  AS pct_gir,
               round(avg(putts), 2)                       AS avg_putts,
               round(sum(penalties)::numeric / count(*), 2) AS penalties_por_hoyo
        FROM seg
        GROUP BY segmento
        ORDER BY sum(score_vs_par) DESC
        """
    )


@app.get("/api/hero")
def hero() -> dict[str, Any]:
    """La ultima vuelta de 18 completa, lista para dibujar la tarjeta."""
    head = q1(
        """
        SELECT r.id, r.started_at, r.strokes, r.par, r.score_vs_par,
               c.name AS course, s.putts, s.greens_in_regulation,
               s.greens_recorded, s.fairways_hit, s.fairways_recorded
        FROM rounds r
        LEFT JOIN courses c USING (course_global_id)
        LEFT JOIN round_stats s ON s.round_id = r.id AND s.segment = 'round'
        WHERE r.is_complete AND r.holes_completed = 18
        ORDER BY r.started_at DESC LIMIT 1
        """
    )
    if head is None:
        raise HTTPException(404, "sin vueltas completas")
    holes = q(
        f"""
        SELECT hole_number, par, strokes, putts, score_vs_par,
               round((straight_m {YD})::numeric, 0) AS length_yd
        FROM holes WHERE round_id = %s ORDER BY hole_number
        """,
        (head["id"],),
    )
    prev = q1(
        """
        SELECT round(avg(score_vs_par), 1) AS avg_vs_par FROM (
            SELECT score_vs_par FROM rounds
            WHERE is_complete AND holes_completed = 18 AND NOT exclude_from_stats
            ORDER BY started_at DESC LIMIT 10 OFFSET 1
        ) t
        """
    )
    return {"round": head, "holes": holes, "avg_vs_par_10": prev["avg_vs_par"] if prev else None}


# ============================================================ login y sync
# La contraseña se usa una sola vez para acuñar el token OAuth y no se guarda
# en ningun lado. Ver session.py.
#
# OJO: esta API no tiene autenticacion propia. Los puertos estan atados a
# 127.0.0.1 en docker-compose justamente por esto: si alguna vez corre en un
# servidor, hay que ponerle auth ANTES de exponerla.

class LoginBody(BaseModel):
    email: str
    password: str


class MfaBody(BaseModel):
    session: str
    code: str


@app.get("/api/auth/status")
def auth_status_endpoint(verify: bool = False) -> dict[str, Any]:
    """Por defecto comprueba local (lee el vencimiento del token guardado).

    `?verify=true` lo chequea contra Garmin, que tarda varios segundos.
    """
    return session.auth_status(verify=verify)


@app.post("/api/auth/login")
def auth_login(body: LoginBody) -> dict[str, Any]:
    if not body.email.strip() or not body.password:
        raise HTTPException(400, "Falta el mail o la contraseña.")
    try:
        return session.start_login(body.email.strip(), body.password)
    except session.RateLimited as exc:
        raise HTTPException(429, str(exc)) from None
    except GarminConnectAuthenticationError:
        raise HTTPException(401, "Garmin rechazó el mail o la contraseña.") from None
    except GarminConnectTooManyRequestsError:
        raise HTTPException(429, "Garmin está limitando los intentos. Esperá unos minutos.") from None
    except Exception as exc:  # noqa: BLE001
        # Nunca devolver el detalle crudo: puede arrastrar partes del request.
        logger.warning("Login fallo: %s", type(exc).__name__)
        raise HTTPException(502, "No se pudo entrar a Garmin. Probá de nuevo.") from None


@app.post("/api/auth/mfa")
def auth_mfa(body: MfaBody) -> dict[str, Any]:
    if not body.code.strip():
        raise HTTPException(400, "Falta el código.")
    try:
        return session.complete_mfa(body.session, body.code.strip())
    except KeyError as exc:
        raise HTTPException(410, str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        logger.warning("MFA fallo: %s", type(exc).__name__)
        raise HTTPException(401, "El código no sirvió. Probá de nuevo.") from None


@app.post("/api/auth/logout")
def auth_logout() -> dict[str, Any]:
    return session.logout()


@app.post("/api/sync")
def sync_start(limit: int | None = None) -> dict[str, Any]:
    if not session.auth_status().get("authenticated"):
        raise HTTPException(401, "Entrá a Garmin antes de sincronizar.")
    return session.start_sync(limit).as_dict()


@app.get("/api/sync")
def sync_current() -> dict[str, Any]:
    job = session.current_job()
    return job.as_dict() if job else {"state": "inactivo"}


@app.get("/api/sync/{job_id}")
def sync_status(job_id: str) -> dict[str, Any]:
    job = session.get_job(job_id)
    if job is None:
        raise HTTPException(404, "No existe ese trabajo.")
    return job.as_dict()


# ------------------------------------------------- nombres de palos (usuario)
# Garmin guarda en `model` el nombre del SET: ocho hierros del mismo juego
# llegan todos como "Ping 430". Quien tiene que ponerles nombre es el jugador,
# que sabe qué hay en su bolsa. Se nombra por RANURA (clubTypeId) para que un
# set nuevo lo herede sin volver a cargar nada.

class ClubLabelBody(BaseModel):
    scope: str = "slot"
    key: str
    label: str


@app.get("/api/club-labels")
def club_labels() -> list[dict[str, Any]]:
    return q("SELECT scope, key, label FROM club_labels ORDER BY scope, key")


@app.put("/api/club-labels")
def set_club_label(body: ClubLabelBody) -> dict[str, Any]:
    """Poner o borrar el nombre de una ranura (o de un palo puntual).

    Escribe también en `clubs` para que el cambio se vea sin recargar el ETL.
    """
    if body.scope not in ("slot", "club"):
        raise HTTPException(400, "scope tiene que ser 'slot' o 'club'")
    label = body.label.strip()
    with connect() as conn, conn.cursor() as cur:
        if label:
            cur.execute(
                """INSERT INTO club_labels (scope, key, label) VALUES (%s,%s,%s)
                   ON CONFLICT (scope, key) DO UPDATE SET label = EXCLUDED.label""",
                (body.scope, body.key, label),
            )
        else:
            cur.execute(
                "DELETE FROM club_labels WHERE scope = %s AND key = %s",
                (body.scope, body.key),
            )
        if body.scope == "slot":
            cur.execute(
                "UPDATE clubs SET label = %s, slot = %s WHERE club_type_id = %s",
                (label or None, label or None, int(body.key)),
            )
        else:
            cur.execute("UPDATE clubs SET label = %s WHERE id = %s",
                        (label or None, int(body.key)))
        conn.commit()
    return {"scope": body.scope, "key": body.key, "label": label or None}
