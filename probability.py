"""Modelo estadístico simple (Poisson) para estimar 1X2 y utilidades de cuotas."""
import math

from sofascore_client import GoalStats

MAX_GOALS = 8
MIN_XG = 0.15
MAX_XG = 5.0


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_goals(home_stats: GoalStats, away_stats: GoalStats) -> tuple[float, float]:
    """Combina el ataque de un equipo con la defensa del rival (estilo Dixon-Coles simplificado)."""
    home_xg = (home_stats.avg_scored_home + away_stats.avg_conceded_away) / 2
    away_xg = (away_stats.avg_scored_away + home_stats.avg_conceded_home) / 2
    home_xg = min(max(home_xg, MIN_XG), MAX_XG)
    away_xg = min(max(away_xg, MIN_XG), MAX_XG)
    return home_xg, away_xg


def match_probabilities(home_xg: float, away_xg: float) -> dict:
    """Devuelve P(1), P(X), P(2) integrando la matriz de resultados de Poisson."""
    home_probs = [_poisson_pmf(i, home_xg) for i in range(MAX_GOALS + 1)]
    away_probs = [_poisson_pmf(j, away_xg) for j in range(MAX_GOALS + 1)]

    p_home = p_draw = p_away = 0.0
    for i, ph in enumerate(home_probs):
        for j, pa in enumerate(away_probs):
            p = ph * pa
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p

    total = p_home + p_draw + p_away
    return {"1": p_home / total, "X": p_draw / total, "2": p_away / total}


def devigged_implied_probabilities(odds: dict) -> dict:
    """Quita el margen de la casa (overround) normalizando las probabilidades implícitas."""
    raw = {k: 1.0 / v for k, v in odds.items() if v}
    overround = sum(raw.values())
    return {k: v / overround for k, v in raw.items()}
