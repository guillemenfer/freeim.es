"""Orquesta la búsqueda de cuotas con valor: Codere (cuotas) vs Sofascore (forma real)."""
import logging
from dataclasses import dataclass
from datetime import datetime

import config
import sofascore_client
from codere_client import CodereMatch, fetch_featured_soccer_matches
from probability import devigged_implied_probabilities, expected_goals, match_probabilities

logger = logging.getLogger(__name__)

OUTCOME_LABEL = {"1": "Local", "X": "Empate", "2": "Visitante"}


def value_bet_to_dict(vb: "ValueBet") -> dict:
    m = vb.match
    return {
        "home": m.home,
        "away": m.away,
        "league": m.league,
        "start_date": m.start_date.isoformat() if m.start_date else None,
        "outcome": vb.outcome,
        "outcome_label": OUTCOME_LABEL[vb.outcome],
        "odd": vb.codere_odd,
        "model_prob": round(vb.model_prob, 4),
        "implied_prob": round(vb.implied_prob, 4),
        "edge": round(vb.edge, 4),
        "home_xg": round(vb.home_xg, 2),
        "away_xg": round(vb.away_xg, 2),
    }


@dataclass
class ValueBet:
    match: CodereMatch
    outcome: str
    codere_odd: float
    model_prob: float
    implied_prob: float
    edge: float
    home_xg: float
    away_xg: float


def _analyze_match(m: CodereMatch) -> list[ValueBet]:
    home_id = sofascore_client.find_team_id(m.home)
    away_id = sofascore_client.find_team_id(m.away)
    if not home_id or not away_id:
        return []

    home_stats = sofascore_client.get_team_goal_stats(home_id)
    away_stats = sofascore_client.get_team_goal_stats(away_id)
    if not home_stats or not away_stats:
        logger.info("Sin historial suficiente para %s vs %s, se omite", m.home, m.away)
        return []

    home_xg, away_xg = expected_goals(home_stats, away_stats)
    model_probs = match_probabilities(home_xg, away_xg)
    implied_probs = devigged_implied_probabilities(m.odds)

    value_bets = []
    for outcome in ("1", "X", "2"):
        odd = m.odds.get(outcome)
        model_p = model_probs.get(outcome)
        implied_p = implied_probs.get(outcome)
        if odd is None or model_p is None or implied_p is None:
            continue
        edge = model_p - implied_p
        if edge >= config.EDGE_THRESHOLD:
            value_bets.append(
                ValueBet(
                    match=m,
                    outcome=outcome,
                    codere_odd=odd,
                    model_prob=model_p,
                    implied_prob=implied_p,
                    edge=edge,
                    home_xg=home_xg,
                    away_xg=away_xg,
                )
            )
    return value_bets


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
