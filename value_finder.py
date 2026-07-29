"""Orquesta la búsqueda de cuotas con valor: Codere (cuotas) vs estadísticas reales.

Evalúa 4 mercados por partido: 1X2, Total de Goles, Ambos Marcan y Total de Córners.
Cada liga usa la fuente de estadísticas configurada en STATS_PROVIDERS (ESPN por
defecto, Flashscore para las que ESPN no cubre bien).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

import config
import probability
import espn_client
import flashscore_client
from codere_client import CodereMatch, fetch_featured_soccer_matches
from probability import (
    btts_probabilities,
    devigged_implied_probabilities,
    expected_corners,
    expected_goals,
    match_probabilities,
    total_corners_probabilities,
    total_goals_probabilities,
)

logger = logging.getLogger(__name__)

OUTCOME_LABEL = {"1": "Local", "X": "Empate", "2": "Visitante"}

_PROVIDERS = {"espn": espn_client, "flashscore": flashscore_client}


def _resolve_provider(league_name: str):
    """Devuelve (módulo_proveedor, identificador_de_liga_para_ese_proveedor) o
    (None, None) si la liga no está configurada en ningún proveedor."""
    provider_name = config.STATS_PROVIDERS.get(league_name)
    if provider_name == "espn":
        return espn_client, config.ESPN_LEAGUE_SLUGS.get(league_name)
    if provider_name == "flashscore":
        return flashscore_client, config.FLASHSCORE_TOURNAMENTS.get(league_name)
    return None, None


@dataclass
class ValueBet:
    match: CodereMatch
    market: str  # "1x2" | "goals" | "btts" | "corners"
    selection_label: str
    codere_odd: float
    model_prob: float
    implied_prob: float
    edge: float
    tags: list[str] = field(default_factory=list)  # "value" y/o "likely"
    context: dict = field(default_factory=dict)


def value_bet_to_dict(vb: "ValueBet") -> dict:
    m = vb.match
    return {
        "home": m.home,
        "away": m.away,
        "league": m.league,
        "start_date": m.start_date.isoformat() if m.start_date else None,
        "market": vb.market,
        "selection_label": vb.selection_label,
        "odd": vb.codere_odd,
        "model_prob": round(vb.model_prob, 4),
        "implied_prob": round(vb.implied_prob, 4),
        "edge": round(vb.edge, 4),
        "tags": vb.tags,
        "context": {k: round(v, 2) if isinstance(v, float) else v for k, v in vb.context.items()},
    }


def _consider(
    match: CodereMatch,
    market: str,
    selection_label: str,
    odd: float | None,
    model_p: float | None,
    implied_p: float | None,
    context: dict,
    out: list["ValueBet"],
) -> None:
    if odd is None or model_p is None or implied_p is None:
        return
    edge = model_p - implied_p

    if edge > config.MAX_TRUSTED_EDGE:
        logger.info(
            "Edge descartado por sospechoso (+%.1f pts) en %s vs %s [%s - %s]: "
            "probablemente error de modelo, no cuota real mal puesta",
            edge * 100, match.home, match.away, market, selection_label,
        )
        has_value = False
    else:
        has_value = edge >= config.EDGE_THRESHOLD

    is_likely = model_p >= config.HIGH_PROB_THRESHOLD
    if not (has_value and is_likely):
        return

    tags = ["value", "likely"]

    out.append(
        ValueBet(
            match=match,
            market=market,
            selection_label=selection_label,
            codere_odd=odd,
            model_prob=model_p,
            implied_prob=implied_p,
            edge=edge,
            tags=tags,
            context=context,
        )
    )


def _analyze_1x2(m: CodereMatch, home_xg: float, away_xg: float, out: list[ValueBet]) -> None:
    model_probs = match_probabilities(home_xg, away_xg)
    implied_probs = devigged_implied_probabilities(m.odds_1x2)
    ctx = {"home_xg": home_xg, "away_xg": away_xg}
    for outcome in ("1", "X", "2"):
        _consider(
            m, "1x2", OUTCOME_LABEL[outcome],
            m.odds_1x2.get(outcome), model_probs.get(outcome), implied_probs.get(outcome),
            ctx, out,
        )


def _analyze_goals(m: CodereMatch, home_xg: float, away_xg: float, out: list[ValueBet]) -> None:
    if not m.odds_goals:
        return
    line = m.odds_goals["line"]
    model_probs = total_goals_probabilities(home_xg, away_xg, line)
    implied_probs = devigged_implied_probabilities({"over": m.odds_goals["over"], "under": m.odds_goals["under"]})
    ctx = {"home_xg": home_xg, "away_xg": away_xg, "line": line}
    _consider(
        m, "goals", f"Más de {line} goles",
        m.odds_goals["over"], model_probs.get("over"), implied_probs.get("over"), ctx, out,
    )
    _consider(
        m, "goals", f"Menos de {line} goles",
        m.odds_goals["under"], model_probs.get("under"), implied_probs.get("under"), ctx, out,
    )


def _analyze_btts(m: CodereMatch, home_xg: float, away_xg: float, out: list[ValueBet]) -> None:
    if not m.odds_btts:
        return
    model_probs = btts_probabilities(home_xg, away_xg)
    implied_probs = devigged_implied_probabilities({"yes": m.odds_btts["yes"], "no": m.odds_btts["no"]})
    ctx = {"home_xg": home_xg, "away_xg": away_xg}
    _consider(
        m, "btts", "Ambos marcan: Sí",
        m.odds_btts["yes"], model_probs.get("yes"), implied_probs.get("yes"), ctx, out,
    )
    _consider(
        m, "btts", "Ambos marcan: No",
        m.odds_btts["no"], model_probs.get("no"), implied_probs.get("no"), ctx, out,
    )


def _analyze_corners(
    m: CodereMatch, provider, identifier: str, home_id, away_id, home_events: list, away_events: list,
    out: list[ValueBet],
) -> None:
    if not m.odds_corners:
        return
    home_corner_stats = provider.compute_corner_stats(home_id, home_events, identifier)
    away_corner_stats = provider.compute_corner_stats(away_id, away_events, identifier)
    if not home_corner_stats or not away_corner_stats:
        logger.info("Sin historial de córners suficiente para %s vs %s, se omite ese mercado", m.home, m.away)
        return

    total_xc = expected_corners(home_corner_stats, away_corner_stats)
    line = m.odds_corners["line"]
    model_probs = total_corners_probabilities(total_xc, line)
    implied_probs = devigged_implied_probabilities({"over": m.odds_corners["over"], "under": m.odds_corners["under"]})
    ctx = {"total_corners_xg": total_xc, "line": line}
    _consider(
        m, "corners", f"Más de {line} córners",
        m.odds_corners["over"], model_probs.get("over"), implied_probs.get("over"), ctx, out,
    )
    _consider(
        m, "corners", f"Menos de {line} córners",
        m.odds_corners["under"], model_probs.get("under"), implied_probs.get("under"), ctx, out,
    )


@dataclass
class RunStats:
    total_matches: int
    teams_attempted: int
    teams_resolved: int

    @property
    def looks_blocked(self) -> bool:
        """Si casi ningún equipo se pudo resolver en las fuentes de estadísticas,
        probablemente no es que realmente no existan (nombres raros aislados sí
        pasan) sino que alguna fuente está bloqueando las peticiones (ej. IP de
        datacenter en GitHub Actions)."""
        if self.teams_attempted < 4:
            return False
        return (self.teams_resolved / self.teams_attempted) < 0.2


def _collect_team_data(matches: list[CodereMatch]) -> tuple[dict[tuple[str, object], dict], int]:
    """Resuelve equipo->id (dentro de la liga que corresponda) y trae su historial
    de goles una sola vez por equipo (varios partidos de una misma ronda pueden
    repetir equipos). Clave: (identificador_de_liga, team_id), para no mezclar
    equipos de ligas/proveedores distintos."""
    team_data: dict[tuple[str, object], dict] = {}
    attempted = set()
    missing_leagues = set()
    for m in matches:
        provider, identifier = _resolve_provider(m.league)
        if not provider or not identifier:
            missing_leagues.add(m.league)
            continue
        for name in (m.home, m.away):
            attempted.add((identifier, name))
            team_id = provider.find_team_id(name, identifier)
            key = (identifier, team_id)
            if not team_id or key in team_data:
                continue
            events = provider.get_recent_finished_events(team_id, identifier)
            goal_stats = provider.compute_goal_stats(team_id, events)
            team_data[key] = {"events": events, "goal_stats": goal_stats}
    if missing_leagues:
        logger.warning(
            "Sin proveedor de estadísticas configurado para: %s (agregalo a STATS_PROVIDERS)",
            ", ".join(missing_leagues),
        )
    return team_data, len(attempted)


def _league_avg_goals_by_league(team_data: dict[tuple[str, object], dict]) -> dict[str, float]:
    """Calibra el promedio de goles 'típico' de cada liga con sus propios equipos,
    en vez de usar una constante mundial (o mezclar ligas más o menos ofensivas que
    el promedio, ej. Argentina y Noruega no anotan igual)."""
    by_league: dict[str, list[float]] = {}
    for (identifier, _team_id), d in team_data.items():
        if d["goal_stats"]:
            by_league.setdefault(identifier, []).append(d["goal_stats"].avg_scored_overall)

    result = {}
    for identifier, avgs in by_league.items():
        result[identifier] = sum(avgs) / len(avgs)
        logger.info(
            "Promedio de goles calibrado para %s: %.2f goles/equipo/partido (sobre %d equipos)",
            identifier, result[identifier], len(avgs),
        )
    return result


def _analyze_match(
    m: CodereMatch, provider, identifier: str, home_id, away_id,
    team_data: dict[tuple[str, object], dict], league_avg_goals: float,
) -> list[ValueBet]:
    home_stats = team_data[(identifier, home_id)]["goal_stats"]
    away_stats = team_data[(identifier, away_id)]["goal_stats"]
    if not home_stats or not away_stats:
        logger.info("Sin historial suficiente para %s vs %s, se omite", m.home, m.away)
        return []

    home_xg, away_xg = expected_goals(home_stats, away_stats, league_avg_goals)

    out: list[ValueBet] = []
    _analyze_1x2(m, home_xg, away_xg, out)
    _analyze_goals(m, home_xg, away_xg, out)
    _analyze_btts(m, home_xg, away_xg, out)
    _analyze_corners(
        m, provider, identifier, home_id, away_id,
        team_data[(identifier, home_id)]["events"], team_data[(identifier, away_id)]["events"],
        out,
    )
    return out


def find_value_bets(now: datetime | None = None) -> tuple[list[ValueBet], RunStats]:
    """Devuelve (selecciones que son cuota-con-valor Y evento-probable a la vez, stats_de_la_corrida)."""
    now = now or datetime.now()
    matches = fetch_featured_soccer_matches()
    matches = [m for m in matches if not m.start_date or m.start_date > now]

    team_data, teams_attempted = _collect_team_data(matches)
    stats = RunStats(total_matches=len(matches), teams_attempted=teams_attempted, teams_resolved=len(team_data))
    if stats.looks_blocked:
        logger.warning(
            "Solo se resolvieron %d/%d equipos: probablemente bloqueado en alguna fuente "
            "(no se publican resultados esta pasada para no pisar el último dato bueno)",
            stats.teams_resolved, stats.teams_attempted,
        )
        return [], stats

    league_avg_goals_map = _league_avg_goals_by_league(team_data)

    all_bets: list[ValueBet] = []
    for m in matches:
        provider, identifier = _resolve_provider(m.league)
        if not provider or not identifier:
            continue
        home_id = provider.find_team_id(m.home, identifier)
        away_id = provider.find_team_id(m.away, identifier)
        if (
            not home_id or not away_id
            or (identifier, home_id) not in team_data
            or (identifier, away_id) not in team_data
        ):
            continue
        league_avg_goals = league_avg_goals_map.get(identifier, probability.DEFAULT_LEAGUE_AVG_GOALS)
        try:
            all_bets.extend(_analyze_match(m, provider, identifier, home_id, away_id, team_data, league_avg_goals))
        except Exception:
            logger.exception("Error analizando %s vs %s", m.home, m.away)

    all_bets.sort(key=lambda vb: vb.edge, reverse=True)
    return all_bets, stats
