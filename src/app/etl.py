"""Capa 2: de los JSON crudos a Postgres.

Lee `data/raw` (nunca la red) y carga canchas, rondas, hoyos, tiros y palos.
Es idempotente: se puede correr las veces que haga falta sobre el mismo raw.

Correr:
    docker compose run --rm etl              # dentro del stack
    uv run python -m app.etl         # desde el host
"""

from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, Config
from .db import connect
from .geo import from_course_scale, from_semicircles
from .hole_length import HoleMeasurement, build_profiles, measure_round, noise_floor_m
from .raw_store import RawStore

logger = logging.getLogger(__name__)

# Umbrales para clasificar la forma del hoyo, en multiplos del piso de ruido
# calibrado en par 3 (ver hole_length.noise_floor_m).
CURVE_FACTOR = 1.5
DOGLEG_FACTOR = 2.5


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _point(coords: tuple[float, float] | None) -> str | None:
    """(lat, lon) -> WKT POINT(lon lat). PostGIS espera lon primero."""
    if coords is None:
        return None
    lat, lon = coords
    return f"POINT({lon} {lat})"


def snapshot_for_round(
    card: dict[str, Any], snaps: list[dict[str, Any]]
) -> dict[str, Any]:
    """El courseSnapshot que la ronda realmente uso.

    Una misma cancha (courseGlobalId) tiene VARIOS snapshots: versiones del
    campo a lo largo del tiempo, con layouts de 9 y de 18 hoyos y pares
    distintos. Agarrar snaps[0] a ciegas da el par equivocado. La tarjeta
    guarda cual estaba vigente en `courseSnapshotId`; matchea en 232/232.
    """
    sid = card.get("courseSnapshotId")
    hit = next((s for s in snaps if s.get("courseSnapshotId") == sid), None)
    if hit is not None:
        return hit
    # Sin match, el mas largo es la apuesta menos mala.
    return max(snaps, key=lambda s: len(s.get("holePars") or ""), default={})


def hole_par(hole_pars: str, number: int) -> int | None:
    """Par del hoyo `number` (1-based), repitiendo ciclicamente.

    Hay canchas de nueve que se juegan dos veces: el snapshot trae 9 pares y
    la ronda tiene 18 hoyos. El hoyo 10 es el 1 otra vez.
    """
    if not hole_pars or number < 1:
        return None
    return int(hole_pars[(number - 1) % len(hole_pars)])


def _epoch_ms(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


class Etl:
    def __init__(self, store: RawStore, config: Any) -> None:
        self.store = store
        self.config = config
        self.courses: dict[int, dict[str, Any]] = {}
        self.snapshot_use: dict[int, dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.snapshots_by_id: dict[int, dict[str, Any]] = {}
        self.tees: dict[tuple[int, str], dict[str, Any]] = {}
        self.measurements: list[HoleMeasurement] = []
        self.n_rounds = 0
        self.n_shots = 0

    # -- lectura del raw -----------------------------------------------------

    def _iter_rounds(self):
        """Ceder (scorecard, snapshots, shot_data) por cada ronda en disco."""
        for path in sorted(self.config.scorecard_dir.glob("*.json")):
            doc = RawStore.read_file(path)
            details = doc.get("scorecardDetails") or []
            if not details:
                logger.warning("Sin scorecardDetails: %s", path.name)
                continue
            card = details[0].get("scorecard") or {}
            if not card.get("id"):
                continue
            shots_path = self.config.shots_dir / f"{card['id']}.json"
            shot_doc = (
                RawStore.read_file(shots_path) if shots_path.exists() else {}
            )
            yield card, details[0], doc.get("courseSnapshots") or [], shot_doc

    # -- carga ---------------------------------------------------------------

    def run(self) -> None:
        with connect() as conn:
            with conn.cursor() as cur:
                self._truncate(cur)
                # Primera pasada: las canchas tienen que existir antes que las
                # rondas (FK). Es barato, son 232 archivos chicos.
                for card, _, snaps, _ in self._iter_rounds():
                    self._collect_course(card, snaps)
                self._resolve_courses()
                self._load_courses(cur)
                # Segunda pasada: rondas, hoyos y tiros.
                for card, detail, snaps, shot_doc in self._iter_rounds():
                    self._load_round(cur, card, detail, snaps, shot_doc)
                self._load_clubs(cur)
                self._load_hole_profiles(cur)
                cur.execute(
                    """INSERT INTO etl_runs
                         (raw_manifest_entries, rounds_loaded, shots_loaded, notes)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        len(self.store.keys_with_prefix("")),
                        self.n_rounds,
                        self.n_shots,
                        "carga completa desde data/raw",
                    ),
                )
            conn.commit()
        logger.info("ETL listo: %d rondas, %d tiros", self.n_rounds, self.n_shots)

    def _truncate(self, cur) -> None:
        """Recarga completa. El raw es la fuente de verdad, la DB es derivada."""
        cur.execute(
            "TRUNCATE courses, course_tees, rounds, round_stats, holes, shots,"
            " clubs, hole_profiles RESTART IDENTITY CASCADE"
        )

    def _collect_course(self, card: dict[str, Any], snaps: list[dict[str, Any]]) -> None:
        used = snapshot_for_round(card, snaps)
        used_id = used.get("courseSnapshotId")
        for snap in snaps:
            gid = snap.get("courseGlobalId")
            sid = snap.get("courseSnapshotId")
            if gid is None or sid is None:
                continue
            self.snapshots_by_id[sid] = snap
            if sid == used_id:
                self.snapshot_use[gid][sid] += 1
            for tee in snap.get("tees") or []:
                name = tee.get("name")
                if name:
                    self.tees[(gid, name)] = tee

    def _resolve_courses(self) -> None:
        """Una fila por cancha, con el snapshot que mas rondas usaron.

        Si no, el nombre sale de cualquier version vieja del campo, que
        suele venir duplicado o con el layout pegado al nombre del club.
        """
        for gid, uses in self.snapshot_use.items():
            best_sid = max(uses.items(), key=lambda kv: kv[1])[0]
            self.courses[gid] = self.snapshots_by_id[best_sid]

    def _load_courses(self, cur) -> None:
        for gid, snap in self.courses.items():
            cur.execute(
                """INSERT INTO courses (course_global_id, name, city, state, country,
                       location, round_par, front_nine_par, back_nine_par,
                       hole_pars, design_year)
                   VALUES (%s,%s,%s,%s,%s, ST_GeogFromText(%s), %s,%s,%s,%s,%s)
                   ON CONFLICT (course_global_id) DO NOTHING""",
                (
                    gid,
                    snap.get("name"),
                    snap.get("city"),
                    snap.get("state"),
                    snap.get("country"),
                    _point(from_course_scale(snap)),
                    snap.get("roundPar"),
                    snap.get("frontNinePar"),
                    snap.get("backNinePar"),
                    snap.get("holePars"),
                    snap.get("designYear"),
                ),
            )
        for (gid, name), tee in self.tees.items():
            cur.execute(
                """INSERT INTO course_tees
                       (course_global_id, name, handicap_type, rating, slope, hole_handicaps)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (
                    gid,
                    name,
                    tee.get("handicapType"),
                    tee.get("rating"),
                    tee.get("slope"),
                    tee.get("holeHandicaps"),
                ),
            )
        logger.info("Canchas: %d, tees: %d", len(self.courses), len(self.tees))

    def _load_round(self, cur, card, detail, snaps, shot_doc) -> None:
        rid = card["id"]
        gid = card.get("courseGlobalId")
        snap = snapshot_for_round(card, snaps)
        hole_pars = snap.get("holePars") or ""

        holes = card.get("holes") or []
        is_complete = bool(holes) and all(h.get("strokes") is not None for h in holes)
        # El par de la ronda es el de los hoyos que REALMENTE jugaste: un 9
        # hoyos en una cancha de 18 no se compara contra par 72.
        played = [
            hole_par(hole_pars, h["number"])
            for h in holes
            if h.get("strokes") is not None and h.get("number")
        ]
        par = sum(p for p in played if p is not None) or None
        hole_shots = shot_doc.get("holeShots") or []
        has_shots = any(h.get("shots") for h in hole_shots)

        cur.execute(
            """INSERT INTO rounds (id, course_global_id, course_name_raw, started_at,
                   ended_at, score_type, round_type, holes_completed, strokes,
                   handicapped_strokes, par, score_vs_par, player_handicap, tee_box,
                   tee_box_rating, tee_box_slope, distance_walked_m, steps_taken,
                   sensor_on_putter, exclude_from_stats, is_complete, has_shot_data)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                rid,
                gid,
                snap.get("name"),
                _ts(card.get("startTime")),
                _ts(card.get("endTime")),
                card.get("scoreType"),
                card.get("roundType"),
                card.get("holesCompleted"),
                card.get("strokes"),
                card.get("handicappedStrokes"),
                par,
                (card.get("strokes") - par) if par and card.get("strokes") else None,
                card.get("playerHandicap"),
                card.get("teeBox"),
                card.get("teeBoxRating"),
                card.get("teeBoxSlope"),
                card.get("distanceWalked"),
                card.get("stepsTaken"),
                card.get("sensorOnPutter"),
                bool(card.get("excludeFromStats")),
                is_complete,
                has_shots,
            ),
        )
        self.n_rounds += 1

        self._load_round_stats(cur, rid, detail)
        measurements = measure_round(rid, gid, hole_pars, hole_shots)
        self.measurements.extend(measurements)
        self._load_holes(cur, rid, card, snap, hole_shots, measurements)
        self._load_shots(cur, rid, hole_shots)

    def _load_round_stats(self, cur, rid, detail) -> None:
        stats = detail.get("scorecardStats") or {}
        mapping = {"round": "round", "frontNine": "front", "backNine": "back"}
        for key, segment in mapping.items():
            s = stats.get(key)
            if not s:
                continue
            cur.execute(
                """INSERT INTO round_stats (round_id, segment, holes_played, strokes,
                       handicapped_strokes, putts, mean_putts_per_hole, chips,
                       greens_in_regulation, greens_recorded, fairways_hit,
                       fairways_left, fairways_right, fairways_recorded,
                       ups_and_downs, holes_eagle, holes_birdie, holes_par,
                       holes_bogey, holes_over_bogey)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    rid, segment, s.get("holesPlayed"), s.get("strokes"),
                    s.get("handicappedStrokes"), s.get("putts"),
                    s.get("meanPuttsPerHole"), s.get("chips"),
                    s.get("greensInRegulation"), s.get("greensRecorded"),
                    s.get("fairwaysHit"), s.get("fairwaysLeft"), s.get("fairwaysRight"),
                    s.get("fairwaysRecorded"), s.get("upsAndDowns"),
                    s.get("holesEagle"), s.get("holesBirdie"), s.get("holesPar"),
                    s.get("holesBogey"), s.get("holesOverBogey"),
                ),
            )

    def _load_holes(self, cur, rid, card, snap, hole_shots, measurements) -> None:
        hole_pars = snap.get("holePars") or ""
        handicaps_raw = ""
        for tee in snap.get("tees") or []:
            if tee.get("handicapType") == "MEN" and tee.get("holeHandicaps"):
                handicaps_raw = tee["holeHandicaps"]
                break

        by_hole = {m.hole_number: m for m in measurements}
        pins = {
            h.get("holeNumber"): from_semicircles(h.get("pinPosition"))
            for h in hole_shots
        }

        for hole in card.get("holes") or []:
            n = hole.get("number")
            if n is None:
                continue
            par = hole_par(hole_pars, n)
            hcp = (
                int(handicaps_raw[(n - 1) * 2 : n * 2])
                if len(handicaps_raw) >= n * 2
                else None
            )
            pin = pins.get(n)
            if pin is None and hole.get("pinPositionLat") is not None:
                pin = from_semicircles(
                    {"lat": hole["pinPositionLat"], "lon": hole.get("pinPositionLon")}
                )
            m = by_hole.get(n)
            cur.execute(
                """INSERT INTO holes (round_id, hole_number, par, hole_handicap,
                       strokes, putts, penalties, fairway_outcome, green_ref,
                       straight_m, corridor_m)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s, ST_GeogFromText(%s), %s,%s)
                   ON CONFLICT (round_id, hole_number) DO NOTHING""",
                (
                    rid, n, par, hcp, hole.get("strokes"), hole.get("putts"),
                    hole.get("penalties"), hole.get("fairwayShotOutcome"),
                    _point(pin),
                    m.straight_m if m else None,
                    m.corridor_m if m else None,
                ),
            )

    def _load_shots(self, cur, rid, hole_shots) -> None:
        for entry in hole_shots:
            for shot in entry.get("shots") or []:
                sid = shot.get("id")
                if sid is None:
                    continue
                start, end = shot.get("startLoc") or {}, shot.get("endLoc") or {}
                club = shot.get("clubId")
                cur.execute(
                    """INSERT INTO shots (id, round_id, hole_number, shot_order,
                           club_id, shot_type, shot_source, auto_shot_type, shot_at,
                           meters, start_loc, start_lie, end_loc, end_lie,
                           exclude_from_stats)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               ST_GeogFromText(%s),%s, ST_GeogFromText(%s),%s,%s)
                       ON CONFLICT (id) DO NOTHING""",
                    (
                        sid, rid, shot.get("holeNumber") or entry.get("holeNumber"),
                        shot.get("shotOrder"),
                        club or None,          # 0 = AutoShot no supo el palo
                        shot.get("shotType"), shot.get("shotSource"),
                        shot.get("autoShotType"), _epoch_ms(shot.get("shotTime")),
                        shot.get("meters"),
                        _point(from_semicircles(start)), start.get("lie"),
                        _point(from_semicircles(end)), end.get("lie"),
                        bool(shot.get("excludeFromStats")),
                    ),
                )
                self.n_shots += 1

    def _club_naming(self, cur) -> tuple[dict[str, str], dict[str, str]]:
        """(nombres por clubTypeId, excepciones por id de palo).

        Salen de la tabla `club_labels`, que el usuario edita desde la UI y
        que el TRUNCATE no toca. Se nombra por RANURA y no por palo: cuando
        cambias de set, el hierro 5 nuevo entra con otro id pero el mismo
        clubTypeId, asi que hereda el nombre sin tocar nada. Los tiros viejos
        quedan en el palo viejo.
        """
        cur.execute("SELECT scope, key, label FROM club_labels")
        slots: dict[str, str] = {}
        overrides: dict[str, str] = {}
        for row in cur.fetchall():
            (slots if row["scope"] == "slot" else overrides)[row["key"]] = row["label"]
        return slots, overrides

    def _load_clubs(self, cur) -> None:
        slots, overrides = self._club_naming(cur)
        try:
            clubs = RawStore.read_file(self.config.stats_dir / "club_stats.json")
        except FileNotFoundError:
            logger.warning("Sin club_stats.json; salteo palos.")
            return
        for club in clubs or []:
            s = club.get("clubStats") or {}
            cur.execute(
                """INSERT INTO clubs (id, label, slot, model, name, club_type_id, flex_type,
                       shaft_length, retired, deleted, shots_count, avg_distance_m,
                       max_recent_m, min_recent_m, max_lifetime_m,
                       pct_fairway_hit, pct_fairway_left, pct_fairway_right,
                       pct_green_hit, pct_green_miss_left, pct_green_miss_right,
                       pct_green_miss_long, pct_green_miss_short)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    club.get("id"),
                    overrides.get(str(club.get("id")))
                    or slots.get(str(club.get("clubTypeId"))),
                    slots.get(str(club.get("clubTypeId"))),
                    club.get("model"), club.get("name"),
                    club.get("clubTypeId"), club.get("flexTypeId"),
                    club.get("shaftLength"), bool(club.get("retired")),
                    bool(club.get("deleted")),
                    s.get("shotsCount"), s.get("averageDistance"),
                    s.get("maximumRecentDistance"), s.get("minimumRecentDistance"),
                    s.get("maxLifetimeDistance"),
                    s.get("percentFairwayHit"), s.get("percentFairwayLeft"),
                    s.get("percentFairwayRight"), s.get("percentGreenHit"),
                    s.get("percentGreenMissLeft"), s.get("percentGreenMissRight"),
                    s.get("percentGreenMissLong"), s.get("percentGreenMissShort"),
                ),
            )
        retired = sum(1 for c in (clubs or []) if c.get("retired"))
        logger.info("Palos: %d (%d retirados)", len(clubs or []), retired)

    def _load_hole_profiles(self, cur) -> None:
        profiles = build_profiles(self.measurements)
        floor = noise_floor_m(profiles)
        logger.info(
            "Perfiles de hoyo: %d (piso de ruido par 3: %s m)",
            len(profiles),
            f"{floor:.1f}" if floor else "n/d",
        )
        for p in profiles:
            shape = None
            if floor and p.dogleg_excess_m is not None:
                if p.dogleg_excess_m > floor * DOGLEG_FACTOR:
                    shape = "dogleg"
                elif p.dogleg_excess_m > floor * CURVE_FACTOR:
                    shape = "curva"
                else:
                    shape = "recto"
            cur.execute(
                """INSERT INTO hole_profiles (course_global_id, hole_number, par,
                       n_rounds, straight_median_m, straight_p10_m, straight_p90_m,
                       corridor_median_m, dogleg_excess_m, shape)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (course_global_id, hole_number) DO NOTHING""",
                (
                    p.course_id, p.hole_number, p.par, p.n,
                    p.straight_median_m, p.straight_p10_m, p.straight_p90_m,
                    p.corridor_median_m, p.dogleg_excess_m, shape,
                ),
            )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
    # El ETL no necesita credenciales de Garmin: solo lee el raw de disco.
    raw = Path(os.getenv("GARMIN_GOLF_RAW_DIR") or (PROJECT_ROOT / "data/raw"))
    if not raw.is_absolute():
        raw = PROJECT_ROOT / raw
    if not raw.exists():
        print(f"No existe el directorio de data cruda: {raw}", file=sys.stderr)
        return 2
    config = Config(email="", password="", tokenstore=Path("/dev/null"), raw_dir=raw)
    store = RawStore(config.raw_dir, config.manifest_path)
    Etl(store, config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
