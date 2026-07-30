"""Cliente para la API interna (no oficial) de Codere.

Usa el mismo endpoint JSON que consume la web/app de Codere para pintar la
portada de apuestas deportivas. No es una API pública documentada: puede
cambiar sin aviso. Se hacen pocas peticiones y espaciadas (ver config.py).
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from http_utils import get_json

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"/Date\((\d+)\)/")
_NUMBER_RE = re.compile(r"(\d+\.?\d*)")


@dataclass
class CodereMatch:
    event_id: str
    home: str
    away: str
    league: str
    start_date: datetime | None
    odds_1x2: dict = field(default_factory=dict)  # {'1':x, 'X':y, '2':z}
    odds_goals: dict | None = None  # {'line':2.5, 'over':x, 'under':y}
    odds_btts: dict | None = None  # {'yes':x, 'no':y}
    odds_corners: dict | None = None  # {'line':8.5, 'over':x, 'under':y}


def _parse_date(raw: str | None) -> datetime | None:
    """Devuelve un datetime consciente de zona horaria (UTC). Antes se usaba
    fromtimestamp() sin tz, que toma la hora local de la máquina que corre el
    script — funciona distinto en tu PC que en GitHub Actions (que usa UTC),
    y hacía que los horarios mostrados en la web quedaran desfasados."""
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)


def _parse_1x2(results: list, home: str, away: str) -> dict | None:
    if len(results) != 3:
        return None
    odds = {}
    for r in results:
        name, odd = r.get("Name"), r.get("Odd")
        if name == home:
            odds["1"] = odd
        elif name == away:
            odds["2"] = odd
        elif name == "X":
            odds["X"] = odd
    return odds if len(odds) == 3 else None


def _parse_over_under(results: list) -> dict | None:
    """Parsea mercados 'Más X.X' / 'Menos X.X' o 'Más de X.X' / 'Menos de X.X'."""
    over = under = line = None
    for r in results:
        name = (r.get("Name") or "").strip().lower()
        m = _NUMBER_RE.search(name)
        if not m:
            continue
        value = float(m.group(1))
        if name.startswith("más") or name.startswith("mas"):
            over, line = r.get("Odd"), value
        elif name.startswith("menos"):
            under, line = r.get("Odd"), value
    if over is not None and under is not None:
        return {"line": line, "over": over, "under": under}
    return None


def _parse_btts(results: list) -> dict | None:
    yes = no = None
    for r in results:
        name = (r.get("Name") or "").strip().lower()
        if name in ("sí", "si"):
            yes = r.get("Odd")
        elif name == "no":
            no = r.get("Odd")
    if yes is not None and no is not None:
        return {"yes": yes, "no": no}
    return None


def _event_to_match(ev: dict, is_live: bool) -> CodereMatch | None:
    if is_live:
        return None  # el modelo es pre-partido, no tiene sentido comparar en vivo
    home = ev.get("ParticipantHome")
    away = ev.get("ParticipantAway")
    if not home or not away:
        return None

    odds_1x2 = odds_goals = odds_btts = odds_corners = None
    for game in ev.get("Games") or []:
        results = game.get("Results") or []
        game_type = game.get("GameType")
        if game_type == config.CODERE_MARKET_1X2:
            odds_1x2 = _parse_1x2(results, home, away)
        elif game_type == config.CODERE_MARKET_TOTAL_GOALS:
            odds_goals = _parse_over_under(results)
        elif game_type == config.CODERE_MARKET_BTTS:
            odds_btts = _parse_btts(results)
        elif game_type == config.CODERE_MARKET_CORNERS:
            odds_corners = _parse_over_under(results)

    if not odds_1x2:
        return None

    return CodereMatch(
        event_id=str(ev.get("NodeId") or ev.get("EventId") or ""),
        home=home,
        away=away,
        league=ev.get("LeagueName") or "",
        start_date=_parse_date(ev.get("StartDate")),
        odds_1x2=odds_1x2,
        odds_goals=odds_goals,
        odds_btts=odds_btts,
        odds_corners=odds_corners,
    )


def fetch_featured_soccer_matches() -> list[CodereMatch]:
    """Trae el fixture completo (no solo lo destacado en portada) de cada liga en
    CODERE_LEAGUE_NODE_IDS, con sus mercados 1X2, Total Goles, Ambos Marcan y Córners
    (los que Codere tenga cargados para cada partido)."""
    game_types = ";".join(
        str(gt)
        for gt in (
            config.CODERE_MARKET_1X2,
            config.CODERE_MARKET_TOTAL_GOALS,
            config.CODERE_MARKET_BTTS,
            config.CODERE_MARKET_CORNERS,
        )
    )

    matches: dict[str, CodereMatch] = {}
    for node_id, league_name in config.CODERE_LEAGUE_NODE_IDS.items():
        events = get_json(config.CODERE_EVENTS_URL, params={"parentId": node_id, "gameTypes": game_types})
        if not events:
            logger.warning("Codere: sin respuesta para la liga %s (nodeId=%s)", league_name, node_id)
            continue
        for ev in events:
            m = _event_to_match(ev, bool(ev.get("isLive")))
            if m:
                matches[m.event_id] = m

    logger.info(
        "Codere: %d partidos encontrados en %s",
        len(matches), ", ".join(config.CODERE_LEAGUE_NODE_IDS.values()),
    )
    return list(matches.values())
