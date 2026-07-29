"""Cliente para la API pública (no oficial) de ESPN, usada como fuente de estadísticas
de fútbol en reemplazo de Sofascore.

Se cambió de Sofascore a ESPN porque Sofascore empezó a bloquear (403) las peticiones
hechas desde las IPs de datacenter de GitHub Actions, mientras que la API de ESPN (un
CDN público enorme, sin protección tipo Cloudflare para bots) respondió sin problema.
No es una API pública documentada oficialmente: puede cambiar sin aviso.
"""
import logging
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import config
from http_utils import get_json

logger = logging.getLogger(__name__)

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

_teams_cache: dict[str, list[dict]] = {}
_team_id_cache: dict[str, int | None] = {}


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return name.lower().strip()


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    ratio = SequenceMatcher(None, na, nb).ratio()
    if len(na) >= 3 and len(nb) >= 3 and (na in nb or nb in na):
        ratio = max(ratio, 0.75)  # ej. "HJK" está contenido en "HJK Helsinki"
    return ratio


def _get_league_teams(league_slug: str) -> list[dict]:
    if league_slug in _teams_cache:
        return _teams_cache[league_slug]
    data = get_json(f"{ESPN_BASE_URL}/{league_slug}/teams", params={"limit": 50})
    teams = []
    if data:
        sports = data.get("sports") or []
        leagues = sports[0].get("leagues") if sports else []
        if leagues:
            for t in leagues[0].get("teams") or []:
                team = t.get("team") or {}
                teams.append({
                    "id": team.get("id"),
                    "name": team.get("displayName"),
                    "short": team.get("shortDisplayName"),
                })
    _teams_cache[league_slug] = teams
    return teams


def find_team_id(name: str, league_slug: str) -> int | None:
    """Busca un equipo por nombre entre los de la liga (lista trae 30 equipos como
    mucho, así que se compara localmente en vez de pedirle 'búsqueda' al servidor)."""
    cache_key = f"{league_slug}:{_normalize(name)}"
    if cache_key in _team_id_cache:
        return _team_id_cache[cache_key]

    teams = _get_league_teams(league_slug)
    best_id, best_score = None, 0.0
    for t in teams:
        for candidate in (t["name"], t["short"]):
            if not candidate:
                continue
            score = _similarity(name, candidate)
            if score > best_score:
                best_score, best_id = score, t["id"]

    if best_id is not None and best_score < config.NAME_MATCH_THRESHOLD:
        logger.warning("Coincidencia débil para '%s' (similitud %.2f) -> descartada", name, best_score)
        best_id = None
    if best_id is None:
        logger.warning("No se encontró equipo en ESPN para '%s'", name)

    result = int(best_id) if best_id is not None else None
    _team_id_cache[cache_key] = result
    return result


def get_recent_finished_events(team_id: int, league_slug: str) -> list[dict]:
    """Últimos partidos finalizados del equipo en esta liga, más recientes primero."""
    data = get_json(f"{ESPN_BASE_URL}/{league_slug}/teams/{team_id}/schedule")
    if not data:
        return []
    events = []
    for e in data.get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        if status.get("completed"):
            events.append(e)
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return events[: config.FORM_MATCHES]


def _team_competitor(event: dict, team_id: int) -> tuple[dict | None, dict | None]:
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    team_c = next((c for c in competitors if str((c.get("team") or {}).get("id")) == str(team_id)), None)
    opp_c = next((c for c in competitors if c is not team_c), None)
    return team_c, opp_c


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
    home_scored, home_conceded = [], []
    away_scored, away_conceded = [], []
    all_scored, all_conceded = [], []

    for e in events:
        team_c, opp_c = _team_competitor(e, team_id)
        if not team_c or not opp_c:
            continue
        team_goals = (team_c.get("score") or {}).get("value")
        opp_goals = (opp_c.get("score") or {}).get("value")
        if team_goals is None or opp_goals is None:
            continue
        team_goals, opp_goals = int(team_goals), int(opp_goals)

        if team_c.get("homeAway") == "home":
            home_scored.append(team_goals)
            home_conceded.append(opp_goals)
        else:
            away_scored.append(team_goals)
            away_conceded.append(opp_goals)
        all_scored.append(team_goals)
        all_conceded.append(opp_goals)

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
    avg_corners_overall: float
    sample_size: int
    home_sample_size: int
    away_sample_size: int


def _event_corner_counts(event_id: str, league_slug: str) -> dict[str, int] | None:
    """{team_id: córners} de un partido finalizado, o None si no hay dato."""
    data = get_json(f"{ESPN_BASE_URL}/{league_slug}/summary", params={"event": event_id})
    if not data:
        return None
    teams = (data.get("boxscore") or {}).get("teams") or []
    result = {}
    for t in teams:
        team_id = str((t.get("team") or {}).get("id"))
        stat = next((s for s in (t.get("statistics") or []) if s.get("name") == "wonCorners"), None)
        if stat is None:
            continue
        try:
            result[team_id] = int(stat.get("displayValue"))
        except (TypeError, ValueError):
            continue
    return result or None


def compute_corner_stats(team_id: int, events: list[dict], league_slug: str) -> CornerStats | None:
    home_for, home_against = [], []
    away_for, away_against = [], []

    for e in events:
        team_c, opp_c = _team_competitor(e, team_id)
        if not team_c or not opp_c:
            continue
        corners = _event_corner_counts(e.get("id"), league_slug)
        if not corners:
            continue
        opp_id = str((opp_c.get("team") or {}).get("id"))
        team_corners = corners.get(str(team_id))
        opp_corners = corners.get(opp_id)
        if team_corners is None or opp_corners is None:
            continue

        if team_c.get("homeAway") == "home":
            home_for.append(team_corners)
            home_against.append(opp_corners)
        else:
            away_for.append(team_corners)
            away_against.append(opp_corners)

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
        avg_corners_overall=overall_avg,
        sample_size=len(home_for) + len(away_for),
        home_sample_size=len(home_for),
        away_sample_size=len(away_for),
    )
