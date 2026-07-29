"""Sesión HTTP compartida con reintentos simples y throttling básico.

Se usa curl_cffi en vez de requests "puro" porque Sofascore filtra por huella
TLS (protección tipo Cloudflare) y rechaza con 403 las conexiones hechas con
la librería requests/urllib3 estándar, aunque se manden headers de
navegador. curl_cffi imita el handshake TLS de Chrome real.
"""
import logging
import time

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

import config

logger = logging.getLogger(__name__)

_session = requests.Session(impersonate="chrome")
_session.headers.update(
    {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
)

_last_request_ts = 0.0


def _throttle():
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    wait = config.REQUEST_DELAY_SECONDS - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def get_json(url: str, params: dict | None = None, retries: int = 3):
    """GET con reintentos exponenciales simples. Devuelve None si falla todo."""
    last_exc = None
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            resp = _session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning("Fallo GET %s (intento %d/%d): %s", url, attempt, retries, exc)
            time.sleep(1.5 * attempt)
    logger.error("No se pudo obtener %s tras %d intentos: %s", url, retries, last_exc)
    return None


def get_text(url: str, headers: dict | None = None, retries: int = 3) -> str | None:
    """GET que devuelve texto plano (para APIs que no responden JSON, ej. Flashscore)."""
    last_exc = None
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            resp = _session.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except RequestException as exc:
            last_exc = exc
            logger.warning("Fallo GET %s (intento %d/%d): %s", url, attempt, retries, exc)
            time.sleep(1.5 * attempt)
    logger.error("No se pudo obtener %s tras %d intentos: %s", url, retries, last_exc)
    return None
