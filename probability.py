"""Modelo estadístico simple (Poisson) para estimar 1X2 y utilidades de cuotas."""
import math

from sofascore_client import GoalStats

MAX_GOALS = 8
MIN_XG = 0.15
MAX_XG = 5.0

# Promedio de goles "típico" de un equipo por partido, usado como ancla para
# suavizar (shrinkage) promedios calculados con pocos partidos. Sin esto, una
# racha corta contra rivales flojos (ej. goleadas en liga chica) infla el
# promedio del equipo muy por encima de lo que sostiene en un cruce parejo.
LEAGUE_AVG_GOALS = 1.35
SHRINKAGE_K = 6  # "partidos fantasma" con los que se pondera el promedio general


def _shrink(avg_value: float, sample_size: int) -> float:
    return (avg_value * sample_size + LEAGUE_AVG_GOALS * SHRINKAGE_K) / (sample_size + SHRINKAGE_K)


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_goals(home_stats: GoalStats, away_stats: GoalStats) -> tuple[float, float]:
    """Combina el ataque de un equipo con la defensa del rival (estilo Dixon-Coles simplificado),
    suavizando cada promedio hacia la media general según cuántos partidos lo respaldan."""
    home_scored = _shrink(home_stats.avg_scored_home, home_stats.home_sample_size)
    away_conceded_away = _shrink(away_stats.avg_conceded_away, away_stats.away_sample_size)
    away_scored = _shrink(away_stats.avg_scored_away, away_stats.away_sample_size)
    home_conceded = _shrink(home_stats.avg_conceded_home, home_stats.home_sample_size)

    home_xg = (home_scored + away_conceded_away) / 2
    away_xg = (away_scored + home_conceded) / 2
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
