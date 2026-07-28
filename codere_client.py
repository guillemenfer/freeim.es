"""Cliente para la API interna (no oficial) de Codere.

Usa el mismo endpoint JSON que consume la web/app de Codere para pintar la
portada de apuestas deportivas. No es una API pública documentada: puede
cambiar sin aviso. Se hacen pocas peticiones y espaciadas (ver config.py).
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import config
from http_utils import get_json

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"/Date\((\d+)\)/")


@dataclass
class CodereMatch:
    event_id: str
    home: str
    away: str
    league: str
    start_date: datetime | None
    odds: dict = field(default_factory=dict)  # {'1': float, 'X': float, '2': float}


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000)


def _extract_1x2(games: list, home: str, away: str) -> dict | None:
    for game in games or []:
        results = game.get("Results") or []
        if game.get("GameType") != 1 or len(results) != 3:
            continue
        odds = {}
        for r in results:
            name = r.get("Name")
            odd = r.get("Odd")
            if name == home:
                odds["1"] = odd
            elif name == away:
                odds["2"] = odd
            elif name == "X":
                odds["X"] = odd
        if len(odds) == 3:
            return odds
    return None


def _event_to_match(ev: dict, is_live: bool) -> CodereMatch | None:
    if is_live:
        return None  # el modelo es pre-partido, no tiene sentido comparar en vivo
    home = ev.get("ParticipantHome")
    away = ev.get("ParticipantAway")
    if not home or not away:
        return None
    odds = _extract_1x2(ev.get("Games") or [], home, away)
    if not odds:
        return None
    return CodereMatch(
        event_id=str(ev.get("NodeId") or ev.get("EventId") or ""),
        home=home,
        away=away,
        league=ev.get("LeagueName") or "",
        start_date=_parse_date(ev.get("StartDate")),
        odds=odds,
    )


def fetch_featured_soccer_matches() -> list[CodereMatch]:
    """Trae los partidos de fútbol destacados/en portada con mercado 1X2."""
    params = {
        "countHomeLiveEvents": 0,
        "gameTypesHomeLiveEvents": 1,
        "sportHandle": "soccer",
        "countHighlightsEvents": config.CODERE_HIGHLIGHTS_COUNT,
        "gameTypesHighlightsEvents": 1,
    }
    data = get_json(config.CODERE_HOME_INFO_URL, params=params)
    if not data:
        return []

    matches: dict[str, CodereMatch] = {}

    for group in data.get("highlightsEvents") or []:
        if group.get("Name") != "Fútbol":
            continue
        for ev in group.get("Events") or []:
            m = _event_to_match(ev, bool(ev.get("isLive")))
            if m:
                matches[m.event_id] = m

    for ev in data.get("marquee") or []:
        if ev.get("SportHandle") != "soccer":
            continue
        game = ev.get("Game")
        if not game:
            continue
        m = _event_to_match({**ev, "Games": [game]}, bool(ev.get("IsLive")))
        if m:
            matches.setdefault(m.event_id, m)

    logger.info("Codere: %d partidos de fútbol con mercado 1X2 encontrados", len(matches))
    return list(matches.values())
