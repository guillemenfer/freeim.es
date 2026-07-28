"""Orquesta la búsqueda de cuotas con valor: Codere (cuotas) vs ESPN (forma real).

Evalúa 4 mercados por partido: 1X2, Total de Goles, Ambos Marcan y Total de Córners.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

import config
import probability
import espn_client
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


@dataclass
class ValueBet:
    match: CodereMatch
    market: str  # "1x2" | "goals" | "btts" | "corners"
    selection_label: str
    codere_odd: float
    model_prob: float
    implied_prob: float
    edge: float
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
    value_out: list["ValueBet"],
    likely_out: list["ValueBet"],
) -> None:
    if odd is None or model_p is None or implied_p is None:
        return
    edge = model_p - implied_p

    bet = ValueBet(
        match=match,
        market=market,
        selection_label=selection_label,
        codere_odd=odd,
        model_prob=model_p,
        implied_prob=implied_p,
        edge=edge,
        context=context,
    )

    if edge > config.MAX_TRUSTED_EDGE:
        logger.info(
            "Edge descartado por sospechoso (+%.1f pts) en %s vs %s [%s - %s]: "
            "probablemente error de modelo, no cuota real mal puesta",
            edge * 100, match.home, match.away, market, selection_label,
        )
    elif edge >= config.EDGE_THRESHOLD:
        value_out.append(bet)

    if model_p >= config.HIGH_PROB_THRESHOLD:
        likely_out.append(bet)


def _analyze_1x2(m: CodereMatch, home_xg: float, away_xg: float, value_out: list[ValueBet], likely_out: list[ValueBet]) -> None:
    model_probs = match_probabilities(home_xg, away_xg)
    implied_probs = devigged_implied_probabilities(m.odds_1x2)
    ctx = {"home_xg": home_xg, "away_xg": away_xg}
    for outcome in ("1", "X", "2"):
        _consider(
            m, "1x2", OUTCOME_LABEL[outcome],
            m.odds_1x2.get(outcome), model_probs.get(outcome), implied_probs.get(outcome),
            ctx, value_out, likely_out,
        )


def _analyze_goals(m: CodereMatch, home_xg: float, away_xg: float, value_out: list[ValueBet], likely_out: list[ValueBet]) -> None:
    if not m.odds_goals:
        return
    line = m.odds_goals["line"]
    model_probs = total_goals_probabilities(home_xg, away_xg, line)
    implied_probs = devigged_implied_probabilities({"over": m.odds_goals["over"], "under": m.odds_goals["under"]})
    ctx = {"home_xg": home_xg, "away_xg": away_xg, "line": line}
    _consider(
        m, "goals", f"Más de {line} goles",
        m.odds_goals["over"], model_probs.get("over"), implied_probs.get("over"), ctx, value_out, likely_out,
    )
    _consider(
        m, "goals", f"Menos de {line} goles",
        m.odds_goals["under"], model_probs.get("under"), implied_probs.get("under"), ctx, value_out, likely_out,
    )


def _analyze_btts(m: CodereMatch, home_xg: float, away_xg: float, value_out: list[ValueBet], likely_out: list[ValueBet]) -> None:
    if not m.odds_btts:
        return
    model_probs = btts_probabilities(home_xg, away_xg)
    implied_probs = devigged_implied_probabilities({"yes": m.odds_btts["yes"], "no": m.odds_btts["no"]})
    ctx = {"home_xg": home_xg, "away_xg": away_xg}
    _consider(
        m, "btts", "Ambos marcan: Sí",
        m.odds_btts["yes"], model_probs.get("yes"), implied_probs.get("yes"), ctx, value_out, likely_out,
    )
    _consider(
        m, "btts", "Ambos marcan: No",
        m.odds_btts["no"], model_probs.get("no"), implied_probs.get("no"), ctx, value_out, likely_out,
    )


def _analyze_corners(
    m: CodereMatch, home_id: int, away_id: int, home_events: list, away_events: list,
    value_out: list[ValueBet], likely_out: list[ValueBet],
) -> None:
    if not m.odds_corners:
        return
    home_corner_stats = espn_client.compute_corner_stats(home_id, home_events)
    away_corner_stats = espn_client.compute_corner_stats(away_id, away_events)
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
        m.odds_corners["over"], model_probs.get("over"), implied_probs.get("over"), ctx, value_out, likely_out,
    )
    _consider(
        m, "corners", f"Menos de {line} córners",
        m.odds_corners["under"], model_probs.get("under"), implied_probs.get("under"), ctx, value_out, likely_out,
    )


@dataclass
class RunStats:
    total_matches: int
    teams_attempted: int
    teams_resolved: int

    @property
    def looks_blocked(self) -> bool:
        """Si casi ningún equipo se pudo resolver en ESPN, probablemente no es que
        realmente no existan (nombres raros aislados sí pasan) sino que ESPN está
        bloqueando las peticiones (ej. IP de datacenter en GitHub Actions)."""
        if self.teams_attempted < 4:
            return False
        return (self.teams_resolved / self.teams_attempted) < 0.2


def _collect_team_data(matches: list[CodereMatch]) -> tuple[dict[int, dict], int]:
    """Resuelve equipo->id y trae su historial de goles una sola vez por equipo
    (varios partidos de una misma ronda pueden repetir equipos)."""
    team_data: dict[int, dict] = {}
    attempted_names: set[str] = set()
    for m in matches:
        for name in (m.home, m.away):
            attempted_names.add(name)
            team_id = espn_client.find_team_id(name)
            if not team_id or team_id in team_data:
                continue
            events = espn_client.get_recent_finished_events(team_id)
            goal_stats = espn_client.compute_goal_stats(team_id, events)
            team_data[team_id] = {"events": events, "goal_stats": goal_stats}
    return team_data, len(attempted_names)


def _league_avg_goals(team_data: dict[int, dict]) -> float:
    """Calibra el promedio de goles 'típico' con los equipos de esta misma liga,
    en vez de usar una constante mundial que puede no calzar (ligas más o menos
    ofensivas que el promedio)."""
    avgs = [d["goal_stats"].avg_scored_overall for d in team_data.values() if d["goal_stats"]]
    if not avgs:
        return probability.DEFAULT_LEAGUE_AVG_GOALS
    league_avg = sum(avgs) / len(avgs)
    logger.info(
        "Promedio de goles calibrado para esta liga: %.2f goles/equipo/partido (sobre %d equipos)",
        league_avg, len(avgs),
    )
    return league_avg


def _analyze_match(
    m: CodereMatch, home_id: int, away_id: int, team_data: dict, league_avg_goals: float
) -> tuple[list[ValueBet], list[ValueBet]]:
    home_stats = team_data[home_id]["goal_stats"]
    away_stats = team_data[away_id]["goal_stats"]
    if not home_stats or not away_stats:
        logger.info("Sin historial suficiente para %s vs %s, se omite", m.home, m.away)
        return [], []

    home_xg, away_xg = expected_goals(home_stats, away_stats, league_avg_goals)

    value_out: list[ValueBet] = []
    likely_out: list[ValueBet] = []
    _analyze_1x2(m, home_xg, away_xg, value_out, likely_out)
    _analyze_goals(m, home_xg, away_xg, value_out, likely_out)
    _analyze_btts(m, home_xg, away_xg, value_out, likely_out)
    _analyze_corners(
        m, home_id, away_id, team_data[home_id]["events"], team_data[away_id]["events"],
        value_out, likely_out,
    )
    return value_out, likely_out


def find_value_bets(now: datetime | None = None) -> tuple[list[ValueBet], list[ValueBet], RunStats]:
    """Devuelve (cuotas_con_valor, eventos_probables, stats_de_la_corrida)."""
    now = now or datetime.now()
    matches = fetch_featured_soccer_matches()
    matches = [m for m in matches if not m.start_date or m.start_date > now]

    team_data, teams_attempted = _collect_team_data(matches)
    stats = RunStats(total_matches=len(matches), teams_attempted=teams_attempted, teams_resolved=len(team_data))
    if stats.looks_blocked:
        logger.warning(
            "Solo se resolvieron %d/%d equipos en ESPN: probablemente bloqueado "
            "(no se publican resultados esta pasada para no pisar el último dato bueno)",
            stats.teams_resolved, stats.teams_attempted,
        )
        return [], [], stats

    league_avg_goals = _league_avg_goals(team_data)

    all_value_bets: list[ValueBet] = []
    all_likely_events: list[ValueBet] = []
    for m in matches:
        home_id = espn_client.find_team_id(m.home)
        away_id = espn_client.find_team_id(m.away)
        if not home_id or not away_id or home_id not in team_data or away_id not in team_data:
            continue
        try:
            value_bets, likely_events = _analyze_match(m, home_id, away_id, team_data, league_avg_goals)
            all_value_bets.extend(value_bets)
            all_likely_events.extend(likely_events)
        except Exception:
            logger.exception("Error analizando %s vs %s", m.home, m.away)

    all_value_bets.sort(key=lambda vb: vb.edge, reverse=True)
    all_likely_events.sort(key=lambda vb: vb.model_prob, reverse=True)
    return all_value_bets, all_likely_events, stats
