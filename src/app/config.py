"""Configuracion: credenciales desde .env y rutas en disco.

Nada de secretos hardcodeados. Todo sale del entorno (o de un .env local,
que esta en .gitignore).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Raiz del repo: .../src/app/config.py -> subir tres niveles
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TOKENSTORE = "~/.garminconnect"
DEFAULT_RAW_DIR = "data/raw"

# Valores de .env.example: si siguen ahi, el .env nunca se completo. Mejor
# fallar local que gastar un intento de login (Garmin ratelimitea fuerte).
PLACEHOLDERS = frozenset({"tu-email@ejemplo.com", "tu-password", "", "changeme"})


class ConfigError(RuntimeError):
    """Falta configuracion obligatoria."""


@dataclass(frozen=True)
class Config:
    email: str
    password: str
    tokenstore: Path
    raw_dir: Path

    @property
    def summary_dir(self) -> Path:
        return self.raw_dir / "summary"

    @property
    def scorecard_dir(self) -> Path:
        return self.raw_dir / "scorecard"

    @property
    def shots_dir(self) -> Path:
        return self.raw_dir / "shots"

    @property
    def stats_dir(self) -> Path:
        return self.raw_dir / "stats"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "_manifest.json"


def load_config() -> Config:
    """Leer .env + entorno y devolver la config validada."""
    load_dotenv(PROJECT_ROOT / ".env")

    email = os.getenv("GARMIN_EMAIL", "").strip()
    password = os.getenv("GARMIN_PASSWORD", "")

    missing = [
        name
        for name, value in (("GARMIN_EMAIL", email), ("GARMIN_PASSWORD", password))
        if value.strip() in PLACEHOLDERS
    ]
    if missing:
        raise ConfigError(
            f"Sin completar en .env: {', '.join(missing)}. "
            f"Edita {PROJECT_ROOT / '.env'} con tus credenciales reales de Garmin."
        )

    tokenstore = Path(
        os.getenv("GARMINTOKENS") or DEFAULT_TOKENSTORE
    ).expanduser()

    raw_dir = Path(os.getenv("GARMIN_GOLF_RAW_DIR") or DEFAULT_RAW_DIR)
    if not raw_dir.is_absolute():
        raw_dir = PROJECT_ROOT / raw_dir

    return Config(
        email=email,
        password=password,
        tokenstore=tokenstore,
        raw_dir=raw_dir,
    )
