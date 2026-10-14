"""Capa 1: bajar data cruda de Garmin a disco.

Uso:
    uv run caddie sync         bajar todo: vueltas, tarjetas, tiros y stats
    uv run caddie sync --limit 10   solo las 10 vueltas mas recientes
    uv run caddie status       que hay bajado, sin tocar la red
    uv run caddie summary      solo el listado de vueltas + su estructura

Es una API reverseada: se le pega una sola vez por recurso y el parseo se
itera offline contra los JSON ya guardados.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from . import bulk, endpoints as ep, probe
from .client import login
from .config import Config, ConfigError, load_config
from .raw_store import RawStore, utc_stamp

logger = logging.getLogger(__name__)

SUMMARY_URL = ep.SUMMARY
SUMMARY_PAGE_SIZE = 500
SUMMARY_MAX_PAGES = 50  # tope de seguridad


def _unwrap_page(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    """Sacar las rondas y el totalRows de una pagina de summary.

    Garmin devuelve [{"pageNumber": 1, "rowsPerPage": N, "totalRows": M,
    "scorecardSummaries": [...]}] — una lista de un elemento.
    """
    node = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(node, dict):
        return [], None
    rounds = node.get("scorecardSummaries")
    if not isinstance(rounds, list):
        rounds = []
    total = node.get("totalRows")
    return rounds, total if isinstance(total, int) else None


def fetch_summary(
    config: Config,
    store: RawStore,
    *,
    client: Any = None,
    page_size: int = SUMMARY_PAGE_SIZE,
    max_pages: int = SUMMARY_MAX_PAGES,
) -> tuple[list[dict[str, Any]], Any]:
    """Paginar el summary completo y guardarlo como un snapshot fechado.

    OJO: no usamos `client.get_golf_summary()`. Manda `start=N` como parametro
    de paginacion y Garmin lo ignora: devuelve siempre la pagina 1, asi que el
    loop baja la misma pagina N veces sin darse cuenta. El parametro real es
    `page` (1-based). Verificado contra la cuenta: con `start` las paginas
    salian identicas, con `page` no.

    El summary se re-baja entero en cada corrida (es barato y los indices se
    corren cuando aparece una ronda nueva). El sync incremental de verdad vive
    en las scorecards y los tiros, cacheados por scorecard-id.
    """
    client = client or login(config)

    pages: list[Any] = []
    rounds: list[dict[str, Any]] = []
    seen: set[Any] = set()
    total_rows: int | None = None

    for page_no in range(1, max_pages + 1):
        params = {"per-page": str(page_size), "page": str(page_no)}
        logger.info("Pidiendo summary page=%d per-page=%d", page_no, page_size)
        payload = client.connectapi(SUMMARY_URL, params=params)
        batch, total = _unwrap_page(payload)
        if total is not None:
            total_rows = total

        fresh = [r for r in batch if r.get("id") not in seen]
        seen.update(r.get("id") for r in fresh)
        rounds.extend(fresh)
        pages.append(payload)
        logger.info(
            "  -> %d rondas (%d nuevas, acumulado %d de %s)",
            len(batch),
            len(fresh),
            len(rounds),
            total_rows if total_rows is not None else "?",
        )

        if not batch or not fresh:
            # Pagina vacia, o Garmin repitio lo mismo que ya teniamos: cortar
            # en vez de girar en falso hasta max_pages.
            break
        if total_rows is not None and len(rounds) >= total_rows:
            break
        if len(batch) < page_size:
            break
    else:
        logger.warning("Corte por max_pages=%d; puede faltar historico.", max_pages)

    if total_rows is not None and len(rounds) != total_rows:
        logger.warning(
            "Garmin dice totalRows=%d pero junte %d rondas unicas.",
            total_rows,
            len(rounds),
        )

    stamp = utc_stamp()
    key = f"summary:{stamp}"
    path = config.summary_dir / f"summary_{stamp}.json"
    raw = pages[0] if len(pages) == 1 else pages
    store.write(
        key,
        path,
        raw,
        endpoint=SUMMARY_URL,
        params={"per-page": page_size, "pages": len(pages)},
    )
    logger.info(
        "Snapshot de summary: %s (%d rondas, %d paginas)", path, len(rounds), len(pages)
    )
    return rounds, raw


def _cmd_summary(args: argparse.Namespace) -> int:
    config = load_config()
    store = RawStore(config.raw_dir, config.manifest_path)
    rounds, raw = fetch_summary(config, store)

    print(f"\nRondas encontradas: {len(rounds)}")
    if not rounds:
        print("No vino ninguna ronda. Revisa el JSON crudo en", config.summary_dir)
        return 1

    print("\n" + probe.describe(raw, title="ESTRUCTURA REAL DEL SUMMARY"))

    if args.show_round:
        import json

        print("\nPRIMERA RONDA, CRUDA Y COMPLETA")
        print("=" * 31)
        print(json.dumps(rounds[0], indent=2, ensure_ascii=False))
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    config = load_config()
    store = RawStore(config.raw_dir, config.manifest_path)
    client = login(config)

    rounds, _ = fetch_summary(config, store, client=client)
    ids = [r["id"] for r in rounds if r.get("id") is not None]
    if args.limit:
        ids = ids[: args.limit]
        print(f"(--limit {args.limit}: solo las {len(ids)} rondas mas recientes)")

    sc_new, sc_old = bulk.fetch_scorecards(client, config, store, ids, force=args.force)
    sh_new, sh_old, sh_empty = bulk.fetch_shots(client, config, store, ids, force=args.force)
    bulk.fetch_stats(client, config, store)

    print()
    print(f"rondas en el summary : {len(rounds)}")
    print(f"scorecards           : {sc_new} nuevas, {sc_old} ya en disco")
    print(f"tiros                : {sh_new} nuevas, {sh_old} ya en disco, {sh_empty} sin ningun tiro")
    print(f"raw en               : {config.raw_dir}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Que hay en disco, sin tocar la red."""
    config = load_config()
    store = RawStore(config.raw_dir, config.manifest_path)
    counts = {
        "summary (snapshots)": len(store.keys_with_prefix("summary:")),
        "scorecards": len(store.keys_with_prefix("scorecard:")),
        "tiros": len(store.keys_with_prefix("shots:")),
        "stats": len(store.keys_with_prefix("club_stats:"))
        + len(store.keys_with_prefix("user_stats:")),
    }
    print(f"raw dir: {config.raw_dir}")
    for label, n in counts.items():
        print(f"  {label:<22} {n:>5}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caddie", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="logging debug")
    sub = parser.add_subparsers(dest="command", required=True)

    p_summary = sub.add_parser("summary", help="bajar el listado completo de rondas")
    p_summary.add_argument(
        "--show-round",
        action="store_true",
        help="imprimir ademas la primera ronda entera, cruda",
    )
    p_summary.set_defaults(func=_cmd_summary)

    p_sync = sub.add_parser(
        "sync", help="bajar todo: summary + scorecards + tiros + stats (incremental)"
    )
    p_sync.add_argument("--force", action="store_true", help="re-bajar lo que ya esta en disco")
    p_sync.add_argument("--limit", type=int, help="solo las N rondas mas recientes")
    p_sync.set_defaults(func=_cmd_sync)

    p_status = sub.add_parser("status", help="que hay bajado (no toca la red)")
    p_status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Error de configuracion: {exc}", file=sys.stderr)
        return 2
    except GarminConnectAuthenticationError as exc:
        print(f"Garmin rechazo el login: {exc}", file=sys.stderr)
        print(
            "Revisa GARMIN_EMAIL / GARMIN_PASSWORD en .env. Si cambiaste la "
            "password, borra el token cacheado y volve a intentar.",
            file=sys.stderr,
        )
        return 3
    except GarminConnectTooManyRequestsError as exc:
        print(f"Garmin esta ratelimiteando: {exc}", file=sys.stderr)
        print("Espera unos minutos antes de reintentar.", file=sys.stderr)
        return 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
