"""Capa 1: persistencia cruda.

Una respuesta de la API = un archivo JSON en disco. El payload se guarda
verbatim bajo la clave `data`; alrededor va un sobre `_meta` con la
procedencia (endpoint logico, parametros, timestamp) para que el parseo
offline de la capa 2 no tenga que adivinar de donde salio cada cosa.

Un manifest (`_manifest.json`) indexa que se bajo y cuando. Es lo que
habilita el sync incremental: si una ronda ya esta en el manifest, no se
le vuelve a pegar a la red.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(moment: datetime | None = None) -> str:
    """Timestamp apto para nombre de archivo: 20261014T120000Z."""
    return (moment or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def _atomic_write(path: Path, text: str) -> None:
    """Escribir completo o no escribir nada (evita JSON truncado si corto el proceso)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class RawStore:
    """Escribe/lee respuestas crudas y mantiene el manifest."""

    def __init__(self, root: Path, manifest_path: Path | None = None) -> None:
        self.root = root
        self.manifest_path = manifest_path or root / "_manifest.json"
        self._manifest = self._load_manifest()

    # ---- manifest ----------------------------------------------------------

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "entries" in data:
                    return data
                logger.warning("Manifest con formato inesperado, se reinicia.")
            except json.JSONDecodeError:
                logger.warning("Manifest corrupto, se reinicia: %s", self.manifest_path)
        return {"version": MANIFEST_VERSION, "entries": {}}

    def _save_manifest(self) -> None:
        _atomic_write(
            self.manifest_path,
            json.dumps(self._manifest, indent=2, sort_keys=True, ensure_ascii=False),
        )

    def has(self, key: str) -> bool:
        """True si esa respuesta ya se bajo y el archivo sigue en disco."""
        entry = self._manifest["entries"].get(key)
        if entry is None:
            return False
        return (self.root / entry["path"]).exists()

    def entry(self, key: str) -> dict[str, Any] | None:
        return self._manifest["entries"].get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self._manifest["entries"] if k.startswith(prefix))

    # ---- escritura ---------------------------------------------------------

    def write(
        self,
        key: str,
        path: Path,
        payload: Any,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Path:
        """Guardar un payload crudo y registrarlo en el manifest."""
        fetched_at = utc_now()
        envelope = {
            "_meta": {
                "key": key,
                "endpoint": endpoint,
                "params": params or {},
                "fetched_at": fetched_at.isoformat(),
            },
            "data": payload,
        }
        text = json.dumps(envelope, indent=2, ensure_ascii=False)
        _atomic_write(path, text)

        rel = path.relative_to(self.root).as_posix()
        self._manifest["entries"][key] = {
            "path": rel,
            "endpoint": endpoint,
            "params": params or {},
            "fetched_at": fetched_at.isoformat(),
            "bytes": len(text.encode("utf-8")),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        self._save_manifest()
        logger.debug("Guardado %s -> %s", key, rel)
        return path

    def fetch_once(
        self,
        key: str,
        path: Path,
        fetcher: Callable[[], Any],
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[Any, bool]:
        """Bajar `key` solo si todavia no esta en disco.

        Devuelve (payload, se_bajo_de_la_red).
        """
        if not force and self.has(key):
            logger.debug("Skip %s (ya en disco)", key)
            return self.read(key), False
        payload = fetcher()
        self.write(key, path, payload, endpoint=endpoint, params=params)
        return payload, True

    # ---- lectura -----------------------------------------------------------

    def read(self, key: str) -> Any:
        """Devolver el payload crudo (sin el sobre) de una entrada del manifest."""
        entry = self._manifest["entries"].get(key)
        if entry is None:
            raise KeyError(f"No hay entrada '{key}' en el manifest")
        return self.read_file(self.root / entry["path"])

    @staticmethod
    def read_file(path: Path) -> Any:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc["data"] if isinstance(doc, dict) and "data" in doc else doc

    def latest(self, prefix: str) -> Any | None:
        """Payload de la entrada mas reciente cuya key arranca con `prefix`."""
        candidates = [
            (entry["fetched_at"], key)
            for key, entry in self._manifest["entries"].items()
            if key.startswith(prefix)
        ]
        if not candidates:
            return None
        _, key = max(candidates)
        return self.read(key)
