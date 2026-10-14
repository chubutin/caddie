"""Login contra Garmin desde la API, y trabajos de sincronizacion.

REGLA: la contraseña se usa UNA vez para acuñar el token OAuth y nunca se
guarda. No va a la base, no se loguea, no vuelve al browser. Lo unico que
queda en disco es el token en el tokenstore, que es exactamente lo que ya
pasaba corriendo el CLI a mano.

El MFA obliga a mantener viva la instancia del cliente entre el pedido de
login y el envio del codigo: con `return_on_mfa=True` la libreria devuelve
("needs_mfa", None) y guarda el estado pendiente en el propio objeto. Por eso
hay un registro de sesiones en memoria del proceso — no se serializa a ningun
lado y se vence sola.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from .config import PROJECT_ROOT, Config

logger = logging.getLogger(__name__)

MFA_SESSION_TTL = 300  # 5 minutos para escribir el codigo
JOB_RETENTION = 3600


def server_config() -> Config:
    """Config sin credenciales: la API no las necesita, las recibe por request."""
    raw = Path(os.getenv("GARMIN_GOLF_RAW_DIR") or (PROJECT_ROOT / "data/raw"))
    if not raw.is_absolute():
        raw = PROJECT_ROOT / raw
    tokenstore = Path(os.getenv("GARMINTOKENS") or "~/.garminconnect").expanduser()
    return Config(email="", password="", tokenstore=tokenstore, raw_dir=raw)


# ------------------------------------------------------------------ sesiones

@dataclass
class PendingMfa:
    client: Garmin
    created_at: float = field(default_factory=time.monotonic)


_pending: dict[str, PendingMfa] = {}
_pending_lock = threading.Lock()


def _sweep_pending() -> None:
    now = time.monotonic()
    with _pending_lock:
        for key in [k for k, v in _pending.items() if now - v.created_at > MFA_SESSION_TTL]:
            _pending.pop(key, None)


def _persist(client: Garmin, config: Config) -> None:
    config.tokenstore.parent.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(config.tokenstore))
    # La contraseña ya cumplio su funcion: no tiene por que seguir en memoria.
    client.password = None


def auth_status() -> dict[str, Any]:
    """Hay un token usable? Devuelve el nombre del perfil si lo hay."""
    config = server_config()
    if not config.tokenstore.exists():
        return {"authenticated": False, "reason": "sin token guardado"}
    try:
        client = Garmin()
        client.login(tokenstore=str(config.tokenstore))
        return {"authenticated": True, "name": client.get_full_name()}
    except Exception as exc:  # noqa: BLE001
        logger.info("Token guardado no sirve: %s", type(exc).__name__)
        return {"authenticated": False, "reason": "el token guardado ya no sirve"}


def start_login(email: str, password: str) -> dict[str, Any]:
    """Primer paso. Devuelve {authenticated} o {needs_mfa, session}."""
    _sweep_pending()
    config = server_config()
    client = Garmin(email=email, password=password, return_on_mfa=True)
    status, _ = client.login(tokenstore=str(config.tokenstore))

    if status == "needs_mfa":
        token = secrets.token_urlsafe(24)
        with _pending_lock:
            _pending[token] = PendingMfa(client=client)
        return {"authenticated": False, "needs_mfa": True, "session": token}

    _persist(client, config)
    return {"authenticated": True, "needs_mfa": False, "name": client.get_full_name()}


def complete_mfa(session: str, code: str) -> dict[str, Any]:
    """Segundo paso: el codigo MFA sobre la MISMA instancia que inicio el login."""
    _sweep_pending()
    with _pending_lock:
        pending = _pending.get(session)
    if pending is None:
        raise KeyError("la sesion de MFA venció o no existe; volvé a empezar")

    config = server_config()
    pending.client.resume_login(None, code)
    _persist(pending.client, config)
    with _pending_lock:
        _pending.pop(session, None)
    return {"authenticated": True, "name": pending.client.get_full_name()}


def logout() -> dict[str, Any]:
    config = server_config()
    existed = config.tokenstore.exists()
    if config.tokenstore.is_dir():
        for f in config.tokenstore.iterdir():
            f.unlink(missing_ok=True)
        config.tokenstore.rmdir()
    elif existed:
        config.tokenstore.unlink(missing_ok=True)
    with _pending_lock:
        _pending.clear()
    return {"authenticated": False, "removed": existed}


# ------------------------------------------------------------------ trabajos

@dataclass
class Job:
    id: str
    state: str = "corriendo"       # corriendo | listo | error
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def log(self, message: str) -> None:
        logger.info("[job %s] %s", self.id, message)
        self.steps.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "steps": self.steps,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def current_job() -> Job | None:
    with _jobs_lock:
        running = [j for j in _jobs.values() if j.state == "corriendo"]
    return running[0] if running else None


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _run_sync(job: Job, limit: int | None) -> None:
    from . import bulk
    from .etl import Etl
    from .fetch import fetch_summary
    from .raw_store import RawStore

    try:
        config = server_config()
        store = RawStore(config.raw_dir, config.manifest_path)

        job.log("Entrando a Garmin con el token guardado")
        client = Garmin()
        client.login(tokenstore=str(config.tokenstore))

        job.log("Bajando el listado de vueltas")
        rounds, _ = fetch_summary(config, store, client=client)
        ids = [r["id"] for r in rounds if r.get("id") is not None]
        if limit:
            ids = ids[:limit]
        job.log(f"{len(rounds)} vueltas en Garmin, {len(ids)} a revisar")

        new_cards, old_cards = bulk.fetch_scorecards(client, config, store, ids)
        job.log(f"Tarjetas: {new_cards} nuevas, {old_cards} ya estaban")

        new_shots, old_shots, empty = bulk.fetch_shots(client, config, store, ids)
        job.log(f"Tiros: {new_shots} vueltas nuevas, {old_shots} ya estaban, {empty} sin tiros")

        bulk.fetch_stats(client, config, store)
        job.log("Stats de palos y jugador al día")

        job.log("Cargando todo en la base")
        etl = Etl(store, config)
        etl.run()
        job.log(f"Listo: {etl.n_rounds} vueltas y {etl.n_shots} tiros en la base")
        job.state = "listo"
    except Exception as exc:  # noqa: BLE001
        job.state = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        job.log("Se cortó: " + job.error)
        logger.warning("Sync fallo:\n%s", traceback.format_exc())
    finally:
        job.finished_at = time.time()


def start_sync(limit: int | None = None) -> Job:
    """Lanza la sincronizacion en segundo plano. Una por vez."""
    running = current_job()
    if running is not None:
        return running

    with _jobs_lock:
        for jid in [
            j.id for j in _jobs.values()
            if j.finished_at and time.time() - j.finished_at > JOB_RETENTION
        ]:
            _jobs.pop(jid, None)
        job = Job(id=secrets.token_urlsafe(8))
        _jobs[job.id] = job

    threading.Thread(target=_run_sync, args=(job, limit), daemon=True).start()
    return job
