"""Capa 1: bajada masiva de scorecards, tiros y stats, con sync incremental.

Cada ronda es una key estable en el manifest (`scorecard:<id>`, `shots:<id>`),
asi que una segunda corrida solo pide lo que falta.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from garminconnect import Garmin

from . import endpoints as ep
from .config import Config
from .raw_store import RawStore

logger = logging.getLogger(__name__)

THROTTLE_SECONDS = 0.4


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _snapshots_for(card: dict[str, Any], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quedarse con los courseSnapshots que referencia esta scorecard.

    En una respuesta batcheada los snapshots vienen compartidos entre rondas
    (10 rondas -> 7 snapshots). Para que cada archivo por ronda sea
    autocontenido y tenga exactamente la misma forma que la respuesta de una
    sola id, re-adjuntamos los que le corresponden.
    """
    wanted_snapshot_ids = {card.get("courseSnapshotId")}
    wanted_course_ids = {
        card.get("courseGlobalId"),
        card.get("frontNineGlobalCourseId"),
        card.get("backNineGlobalCourseId"),
    }
    wanted_snapshot_ids.discard(None)
    wanted_course_ids.discard(None)

    matched = [
        snap
        for snap in snapshots
        if snap.get("courseSnapshotId") in wanted_snapshot_ids
        or snap.get("courseGlobalId") in wanted_course_ids
    ]
    if not matched:
        logger.warning(
            "Ronda %s sin courseSnapshot asociado (courseSnapshotId=%s)",
            card.get("id"),
            card.get("courseSnapshotId"),
        )
    return matched


def fetch_scorecards(
    client: Garmin,
    config: Config,
    store: RawStore,
    round_ids: list[int],
    *,
    batch_size: int = ep.SCORECARD_BATCH_SIZE,
    force: bool = False,
) -> tuple[int, int]:
    """Bajar el detalle de cada ronda. Devuelve (bajadas, salteadas)."""
    pending = [rid for rid in round_ids if force or not store.has(f"scorecard:{rid}")]
    skipped = len(round_ids) - len(pending)
    if not pending:
        logger.info("Scorecards: nada que bajar (%d ya en disco)", skipped)
        return 0, skipped

    logger.info(
        "Scorecards: %d a bajar, %d ya en disco (%d requests de a %d)",
        len(pending),
        skipped,
        -(-len(pending) // batch_size),
        batch_size,
    )

    downloaded = 0
    for batch_no, batch in enumerate(_chunks(pending, batch_size), start=1):
        ids_param = "-".join(str(i) for i in batch)
        payload = client.connectapi(
            ep.SCORECARD_DETAIL,
            params={"scorecard-ids": ids_param, "include-longest-shot-distance": "true"},
        )
        node = payload[0] if isinstance(payload, list) and payload else payload
        details = node.get("scorecardDetails", []) if isinstance(node, dict) else []
        snapshots = node.get("courseSnapshots", []) if isinstance(node, dict) else []

        got_ids = set()
        for detail in details:
            card = detail.get("scorecard", {})
            rid = card.get("id")
            if rid is None:
                continue
            got_ids.add(rid)
            # Misma forma que la respuesta de una sola id, para que la capa 2
            # no tenga que distinguir de que corrida salio el archivo.
            per_round = {
                "courseSnapshots": _snapshots_for(card, snapshots),
                "scorecardDetails": [detail],
            }
            store.write(
                f"scorecard:{rid}",
                config.scorecard_dir / f"{rid}.json",
                per_round,
                endpoint=ep.SCORECARD_DETAIL,
                params={"scorecard-ids": rid, "batched_with": ids_param},
            )
            downloaded += 1

        missing = set(batch) - got_ids
        if missing:
            logger.warning("Batch %d: Garmin no devolvio %s", batch_no, sorted(missing))

        logger.info("  batch %d: %d/%d rondas (total %d)", batch_no, len(got_ids), len(batch), downloaded)
        time.sleep(THROTTLE_SECONDS)

    return downloaded, skipped


def fetch_shots(
    client: Garmin,
    config: Config,
    store: RawStore,
    round_ids: list[int],
    *,
    force: bool = False,
) -> tuple[int, int, int]:
    """Bajar los tiros de cada ronda. Devuelve (bajadas, salteadas, vacias).

    No se puede batchear: el scorecard-id va en el path. Tampoco se filtra por
    hoyo (Garmin descarta los hoyos 10-18 cuando se manda `hole-numbers`).
    """
    pending = [rid for rid in round_ids if force or not store.has(f"shots:{rid}")]
    skipped = len(round_ids) - len(pending)
    if not pending:
        logger.info("Tiros: nada que bajar (%d ya en disco)", skipped)
        return 0, skipped, 0

    logger.info("Tiros: %d a bajar, %d ya en disco (1 request c/u)", len(pending), skipped)

    downloaded = empty = 0
    for n, rid in enumerate(pending, start=1):
        url = ep.SHOTS.format(scorecard_id=rid)
        try:
            payload = client.connectapi(url)
        except Exception as exc:  # noqa: BLE001 - una ronda rota no corta la bajada
            logger.warning("Ronda %s: fallo el fetch de tiros (%s)", rid, exc)
            continue

        hole_shots = payload.get("holeShots", []) if isinstance(payload, dict) else []
        n_shots = sum(len(h.get("shots", [])) for h in hole_shots)
        if n_shots == 0:
            empty += 1

        store.write(
            f"shots:{rid}",
            config.shots_dir / f"{rid}.json",
            payload,
            endpoint=url,
            params={"scorecard_id": rid},
        )
        downloaded += 1
        if n % 25 == 0 or n == len(pending):
            logger.info("  %d/%d rondas (%d sin tiros hasta ahora)", n, len(pending), empty)
        time.sleep(THROTTLE_SECONDS)

    return downloaded, skipped, empty


def fetch_stats(client: Garmin, config: Config, store: RawStore) -> None:
    """Club stats y user stats: snapshots del estado actual, se re-bajan siempre."""
    club = client.get_golf_club_stats()
    store.write(
        "club_stats:latest",
        config.stats_dir / "club_stats.json",
        club,
        endpoint=ep.CLUB_STATS,
        params={"include-stats": "true"},
    )
    user = client.get_golf_user_stats()
    store.write(
        "user_stats:latest",
        config.stats_dir / "user_stats.json",
        user,
        endpoint=ep.USER_STATS,
    )
    n_clubs = len(club) if isinstance(club, list) else "?"
    logger.info("Stats: %s palos + user stats", n_clubs)
