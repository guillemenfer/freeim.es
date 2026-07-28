"""Cliente para la API interna (no oficial) de Sofascore.

Se usa para resolver el id de un equipo por nombre y para leer su historial
reciente de goles y córners a favor/en contra. Igual que con Codere, no es
una API pública documentada.
"""
import logging
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import config
from http_utils import get_json

logger = logging.getLogger(__name__)

_team_id_cache: dict[str, int | None] = {}


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return name.lower().strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def find_team_id(name: str) -> int | None:
    """Busca un equipo de fútbol por nombre y devuelve el id de Sofascore más parecido."""
    cache_key = _normalize(name)
    if cache_key in _team_id_cache:
        return _team_id_cache[cache_key]

    data = get_json(f"{config.SOFASCORE_BASE_URL}/search/all", params={"q": name, "page": 0})
    team_id = None
    best_score = 0.0
    if data:
        for item in data.get("results") or []:
            if item.get("type") != "team":
                continue
            entity = item.get("entity") or {}
            sport = (entity.get("sport") or {}).get("slug")
            if sport != "football":
                continue
            score = _similarity(name, entity.get("name", ""))
            if score > best_score:
                best_score = score
                team_id = entity.get("id")

    if team_id is not None and best_score < config.NAME_MATCH_THRESHOLD:
        logger.warning(
            "Coincidencia débil para '%s' (similitud %.2f) -> descartada", name, best_score
        )
        team_id = None

    if team_id is None:
        logger.warning("No se encontró equipo en Sofascore para '%s'", name)

    _team_id_cache[cache_key] = team_id
    return team_id


def _is_friendly(event: dict) -> bool:
    """Amistosos (pretemporada, exhibición) meten goleadas contra rivales muy débiles
    que no representan el nivel real del equipo, así que se descartan de la muestra."""
    tournament = event.get("tournament") or {}
    name = (tournament.get("name") or "").lower()
    category = ((tournament.get("category") or {}).get("name") or "").lower()
    return "friendly" in name or "friendlies" in category


def get_recent_finished_events(team_id: int) -> list[dict]:
    """Últimos partidos finalizados del equipo (sin amistosos), más recientes primero."""
    data = get_json(f"{config.SOFASCORE_BASE_URL}/team/{team_id}/events/last/0")
    if not data:
        return []
    events = [
        e
        for e in (data.get("events") or [])
        if (e.get("status") or {}).get("type") == "finished" and not _is_friendly(e)
    ]
    return events[: config.FORM_MATCHES]


@dataclass
class GoalStats:
    avg_scored_home: float
    avg_conceded_home: float
    avg_scored_away: float
    avg_conceded_away: float
    avg_scored_overall: float
    avg_conceded_overall: float
    sample_size: int
    home_sample_size: int
    away_sample_size: int


def compute_goal_stats(team_id: int, events: list[dict]) -> GoalStats | None:
    """Calcula promedios de goles a favor/en contra a partir de una lista de partidos ya traída."""
    home_scored, home_conceded = [], []
    away_scored, away_conceded = [], []
    all_scored, all_conceded = [], []

    for ev in events:
        home_team = (ev.get("homeTeam") or {}).get("id")
        away_team = (ev.get("awayTeam") or {}).get("id")
        home_goals = (ev.get("homeScore") or {}).get("current")
        away_goals = (ev.get("awayScore") or {}).get("current")
        if home_goals is None or away_goals is None:
            continue

        if home_team == team_id:
            home_scored.append(home_goals)
            home_conceded.append(away_goals)
            all_scored.append(home_goals)
            all_conceded.append(away_goals)
        elif away_team == team_id:
            away_scored.append(away_goals)
            away_conceded.append(home_goals)
            all_scored.append(away_goals)
            all_conceded.append(home_goals)

    if not all_scored:
        return None

    def avg(values, fallback):
        return sum(values) / len(values) if values else fallback

    overall_scored_avg = avg(all_scored, 1.2)
    overall_conceded_avg = avg(all_conceded, 1.2)

    return GoalStats(
        avg_scored_home=avg(home_scored, overall_scored_avg),
        avg_conceded_home=avg(home_conceded, overall_conceded_avg),
        avg_scored_away=avg(away_scored, overall_scored_avg),
        avg_conceded_away=avg(away_conceded, overall_conceded_avg),
        avg_scored_overall=overall_scored_avg,
        avg_conceded_overall=overall_conceded_avg,
        sample_size=len(all_scored),
        home_sample_size=len(home_scored),
        away_sample_size=len(away_scored),
    )


@dataclass
class CornerStats:
    avg_corners_home: float
    avg_corners_conceded_home: float
    avg_corners_away: float
    avg_corners_conceded_away: float
    sample_size: int
    home_sample_size: int
    away_sample_size: int


def _event_corner_counts(event_id: int) -> tuple[int, int] | None:
    """Córners (local, visitante) de un partido finalizado, o None si no hay dato."""
    data = get_json(f"{config.SOFASCORE_BASE_URL}/event/{event_id}/statistics")
    if not data:
        return None
    for period in data.get("statistics") or []:
        for group in period.get("groups") or []:
            for item in group.get("statisticsItems") or []:
                if item.get("name") == "Corner kicks":
                    try:
                        return int(item.get("home")), int(item.get("away"))
                    except (TypeError, ValueError):
                        return None
    return None


def compute_corner_stats(team_id: int, events: list[dict]) -> CornerStats | None:
    """Calcula promedios de córners a favor/en contra pidiendo las estadísticas de cada
    partido reciente ya traído (una petición extra por partido)."""
    home_for, home_against = [], []
    away_for, away_against = [], []

    for ev in events:
        home_team = (ev.get("homeTeam") or {}).get("id")
        away_team = (ev.get("awayTeam") or {}).get("id")
        counts = _event_corner_counts(ev.get("id"))
        if counts is None:
            continue
        home_corners, away_corners = counts

        if home_team == team_id:
            home_for.append(home_corners)
            home_against.append(away_corners)
        elif away_team == team_id:
            away_for.append(away_corners)
            away_against.append(home_corners)

    if not home_for and not away_for:
        return None

    def avg(values, fallback):
        return sum(values) / len(values) if values else fallback

    overall = (home_for + away_for) or [config.LEAGUE_AVG_CORNERS]
    overall_avg = sum(overall) / len(overall)
    overall_against = (home_against + away_against) or [config.LEAGUE_AVG_CORNERS]
    overall_against_avg = sum(overall_against) / len(overall_against)

    return CornerStats(
        avg_corners_home=avg(home_for, overall_avg),
        avg_corners_conceded_home=avg(home_against, overall_against_avg),
        avg_corners_away=avg(away_for, overall_avg),
        avg_corners_conceded_away=avg(away_against, overall_against_avg),
        sample_size=len(home_for) + len(away_for),
        home_sample_size=len(home_for),
        away_sample_size=len(away_for),
    )
