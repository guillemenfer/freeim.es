"""Cliente para la API interna (no oficial) de Sofascore.

Se usa únicamente para resolver el id de un equipo por nombre y para leer
su historial reciente de goles marcados/recibidos. Igual que con Codere, no
es una API pública documentada.
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


@dataclass
class GoalStats:
    avg_scored_home: float
    avg_conceded_home: float
    avg_scored_away: float
    avg_conceded_away: float
    avg_scored_overall: float
    avg_conceded_overall: float
    sample_size: int


def get_team_goal_stats(team_id: int) -> GoalStats | None:
    """Calcula promedios de goles a favor/en contra de los últimos partidos finalizados."""
    data = get_json(f"{config.SOFASCORE_BASE_URL}/team/{team_id}/events/last/0")
    if not data:
        return None

    events = [e for e in (data.get("events") or []) if (e.get("status") or {}).get("type") == "finished"]
    events = events[: config.FORM_MATCHES]
    if not events:
        return None

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
    )
