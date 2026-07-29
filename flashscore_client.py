"""Cliente para la API interna (no oficial) de Flashscore, usada como fuente de
estadísticas para ligas que ESPN no cubre bien (ej. Veikkausliiga de Finlandia,
que en ESPN devuelve una temporada vacía/desactualizada del año 2000).

Formato de datos propio de Flashscore ("CAMPO÷valor" separados por "¬", agrupados
en bloques separados por "~"), no JSON, y sin documentación oficial. Se reconstruyó
inspeccionando el tráfico real que genera flashscore.com al abrir la tabla de una
liga. Requiere el header 'x-fsign': es un token fijo público que usa el propio
frontend de Flashscore para todos los visitantes, no es una credencial de nadie.

El feed de "Standings" trae, para cada equipo, sus estadísticas de la tabla y sus
últimos partidos ya embebidos — no hace falta pedir nada más por equipo. No incluye
córners, así que ese mercado no está disponible para las ligas que usan esta fuente.
"""
import logging
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import config
from espn_client import CornerStats, GoalStats
from http_utils import get_text

logger = logging.getLogger(__name__)

FLASHSCORE_FEED_URL = "https://2.flashscore.ninja/2/x/feed/to_{tournament_id}_{stage_id}_1"
FSIGN = "SW9D1eZo"

_feed_cache: dict[str, list[dict]] = {}
_team_id_cache: dict[str, str | None] = {}


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return name.lower().strip()


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    ratio = SequenceMatcher(None, na, nb).ratio()
    if len(na) >= 3 and len(nb) >= 3 and (na in nb or nb in na):
        ratio = max(ratio, 0.75)  # ej. "HJK" está contenido en "HJK Helsinki"
    return ratio


def _parse_feed(text: str) -> list[dict]:
    """Parsea el formato propio de Flashscore en una lista de equipos, cada uno
    con sus últimos partidos ("matches") embebidos."""
    teams: list[dict] = []
    current_team: dict | None = None
    current_match: dict | None = None

    for token in text.split("¬"):
        token = token.lstrip("~")
        if "÷" not in token:
            continue
        key, _, value = token.partition("÷")

        if key == "TR":  # arranca un equipo nuevo de la tabla
            current_team = {"matches": []}
            teams.append(current_team)
            current_match = None
        if current_team is None:
            continue
        if key == "LMS":  # arranca un partido reciente nuevo
            current_match = {}
            current_team["matches"].append(current_match)

        target = current_match if current_match is not None else current_team
        target[key] = value

    return teams


def _get_teams(identifier: str) -> list[dict]:
    """identifier = 'tournamentId:tournamentStageId'."""
    if identifier in _feed_cache:
        return _feed_cache[identifier]
    tournament_id, _, stage_id = identifier.partition(":")
    url = FLASHSCORE_FEED_URL.format(tournament_id=tournament_id, stage_id=stage_id)
    text = get_text(url, headers={"x-fsign": FSIGN})
    teams = _parse_feed(text) if text else []
    if not teams:
        logger.warning("Flashscore: sin datos para tournamentId=%s", identifier)
    _feed_cache[identifier] = teams
    return teams


def find_team_id(name: str, identifier: str) -> str | None:
    cache_key = f"{identifier}:{_normalize(name)}"
    if cache_key in _team_id_cache:
        return _team_id_cache[cache_key]

    teams = _get_teams(identifier)
    best_id, best_score = None, 0.0
    for t in teams:
        team_name = t.get("TN")
        if not team_name:
            continue
        score = _similarity(name, team_name)
        if score > best_score:
            best_score, best_id = score, t.get("TI")

    if best_id is not None and best_score < config.NAME_MATCH_THRESHOLD:
        logger.warning("Coincidencia débil para '%s' (similitud %.2f) -> descartada", name, best_score)
        best_id = None
    if best_id is None:
        logger.warning("No se encontró equipo en Flashscore para '%s'", name)

    _team_id_cache[cache_key] = best_id
    return best_id


def get_recent_finished_events(team_id: str, identifier: str) -> list[dict]:
    """Ya vienen embebidos en el feed de la tabla, no hace falta pedir por partido."""
    teams = _get_teams(identifier)
    team = next((t for t in teams if t.get("TI") == team_id), None)
    if not team:
        return []
    finished = [m for m in team["matches"] if m.get("LMF") not in (None, "") and m.get("LMG") not in (None, "")]
    return finished[: config.FORM_MATCHES]


def compute_goal_stats(team_id: str, events: list[dict]) -> GoalStats | None:
    home_scored, home_conceded = [], []
    away_scored, away_conceded = [], []
    all_scored, all_conceded = [], []

    for m in events:
        try:
            home_goals, away_goals = int(m["LMF"]), int(m["LMG"])
        except (KeyError, ValueError):
            continue

        if m.get("LMH") == team_id:
            home_scored.append(home_goals)
            home_conceded.append(away_goals)
            all_scored.append(home_goals)
            all_conceded.append(away_goals)
        elif m.get("LMA") == team_id:
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


def compute_corner_stats(team_id: str, events: list[dict], identifier: str) -> CornerStats | None:
    """Este feed de Flashscore no trae córners; el mercado se omite para estas ligas."""
    return None
