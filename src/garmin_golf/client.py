"""Login contra Garmin Connect con cache de token y soporte de MFA.

El flujo es el mismo SSO que usa la app de Android (via garth). La libreria
persiste los tokens sola cuando se le pasa `tokenstore` como path: el primer
login pide password (y MFA si la cuenta lo tiene activado), los siguientes
levantan el token de disco sin tocar el SSO.
"""

from __future__ import annotations

import logging
import sys
from getpass import getpass

from garminconnect import Garmin

from .config import Config, load_config

logger = logging.getLogger(__name__)


def _prompt_mfa() -> str:
    """Pedir el codigo MFA por stdin.

    Solo se invoca si Garmin efectivamente lo pide, asi que sirve igual para
    cuentas con y sin MFA. Si no hay TTY (cron, CI) falla con un mensaje claro
    en vez de colgarse esperando input.
    """
    if not sys.stdin.isatty():
        raise RuntimeError(
            "Garmin pidio un codigo MFA pero no hay terminal interactiva. "
            "Corre el login una vez a mano para generar el token cacheado."
        )
    print("\nGarmin pide un codigo MFA (app / SMS / email).", file=sys.stderr)
    code = getpass("Codigo MFA: ").strip()
    if not code:
        raise RuntimeError("No se ingreso ningun codigo MFA.")
    return code


def login(config: Config | None = None) -> Garmin:
    """Devolver un cliente Garmin autenticado.

    Reusa el token de `config.tokenstore` si sigue valido; si no, hace login
    completo con credenciales (+ MFA si corresponde) y lo vuelve a cachear.
    """
    config = config or load_config()
    config.tokenstore.parent.mkdir(parents=True, exist_ok=True)

    client = Garmin(
        email=config.email,
        password=config.password,
        prompt_mfa=_prompt_mfa,
    )
    client.login(tokenstore=str(config.tokenstore))

    who = client.get_full_name() or config.email
    logger.info("Autenticado como %s (token en %s)", who, config.tokenstore)
    return client
