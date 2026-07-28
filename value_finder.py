"""Orquesta la búsqueda de cuotas con valor: Codere (cuotas) vs Sofascore (forma real).

Evalúa 4 mercados por partido: 1X2, Total de Goles, Ambos Marcan y Total de Córners.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

import config
import sofascore_client
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
        return
    if edge >= config.EDGE_THRESHOLD:
        out.append(
            ValueBet(
                match=match,
                market=market,
                selection_label=selection_label,
                codere_odd=odd,
                model_prob=model_p,
                implied_prob=implied_p,
                edge=edge,
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


def _analyze_corners(m: CodereMatch, home_id: int, away_id: int, home_events: list, away_events: list, out: list[ValueBet]) -> None:
    if not m.odds_corners:
        return
    home_corner_stats = sofascore_client.compute_corner_stats(home_id, home_events)
    away_corner_stats = sofascore_client.compute_corner_stats(away_id, away_events)
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


def _analyze_match(m: CodereMatch) -> list[ValueBet]:
    home_id = sofascore_client.find_team_id(m.home)
    away_id = sofascore_client.find_team_id(m.away)
    if not home_id or not away_id:
        return []

    home_events = sofascore_client.get_recent_finished_events(home_id)
    away_events = sofascore_client.get_recent_finished_events(away_id)
    home_stats = sofascore_client.compute_goal_stats(home_id, home_events)
    away_stats = sofascore_client.compute_goal_stats(away_id, away_events)
    if not home_stats or not away_stats:
        logger.info("Sin historial suficiente para %s vs %s, se omite", m.home, m.away)
        return []

    home_xg, away_xg = expected_goals(home_stats, away_stats)

    out: list[ValueBet] = []
    _analyze_1x2(m, home_xg, away_xg, out)
    _analyze_goals(m, home_xg, away_xg, out)
    _analyze_btts(m, home_xg, away_xg, out)
    _analyze_corners(m, home_id, away_id, home_events, away_events, out)
    return out


def find_value_bets(now: datetime | None = None) -> list[ValueBet]:
    now = now or datetime.now()
    matches = fetch_featured_soccer_matches()
    matches = [m for m in matches if not m.start_date or m.start_date > now]

    all_value_bets: list[ValueBet] = []
    for m in matches:
        try:
            all_value_bets.extend(_analyze_match(m))
        except Exception:
            logger.exception("Error analizando %s vs %s", m.home, m.away)

    all_value_bets.sort(key=lambda vb: vb.edge, reverse=True)
    return all_value_bets
