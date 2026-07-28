"""Modelo estadístico simple (Poisson) para estimar 1X2, goles, ambos marcan,
córners y utilidades de cuotas."""
import math

from espn_client import CornerStats, GoalStats

MAX_GOALS = 8
MAX_CORNERS = 25
MIN_XG = 0.15
MAX_XG = 5.0

# Promedios usados como ancla para suavizar (shrinkage) promedios calculados con pocos
# partidos. Sin esto, una racha corta contra rivales flojos (ej. goleadas en liga chica)
# infla el promedio del equipo muy por encima de lo que sostiene en un cruce parejo.
# Se recalculan a partir de los propios equipos de la liga que se está analizando (ver
# value_finder.py), en vez de usar una constante "mundial" que puede no calzar con ligas
# más o menos ofensivas que el promedio (ej. Argentina suele ser más defensiva).
DEFAULT_LEAGUE_AVG_GOALS = 1.35
DEFAULT_LEAGUE_AVG_CORNERS = 5.0
SHRINKAGE_K = 6  # "partidos fantasma" con los que se pondera el promedio general


def _shrink(avg_value: float, sample_size: int, prior: float) -> float:
    return (avg_value * sample_size + prior * SHRINKAGE_K) / (sample_size + SHRINKAGE_K)


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _poisson_cdf(k: int, lam: float) -> float:
    return sum(_poisson_pmf(i, lam) for i in range(k + 1))


def expected_goals(
    home_stats: GoalStats, away_stats: GoalStats, league_avg_goals: float = DEFAULT_LEAGUE_AVG_GOALS
) -> tuple[float, float]:
    """Combina el ataque de un equipo con la defensa del rival (estilo Dixon-Coles simplificado),
    suavizando cada promedio hacia la media de la liga según cuántos partidos lo respaldan."""
    home_scored = _shrink(home_stats.avg_scored_home, home_stats.home_sample_size, league_avg_goals)
    away_conceded_away = _shrink(away_stats.avg_conceded_away, away_stats.away_sample_size, league_avg_goals)
    away_scored = _shrink(away_stats.avg_scored_away, away_stats.away_sample_size, league_avg_goals)
    home_conceded = _shrink(home_stats.avg_conceded_home, home_stats.home_sample_size, league_avg_goals)

    home_xg = (home_scored + away_conceded_away) / 2
    away_xg = (away_scored + home_conceded) / 2
    home_xg = min(max(home_xg, MIN_XG), MAX_XG)
    away_xg = min(max(away_xg, MIN_XG), MAX_XG)
    return home_xg, away_xg


def expected_corners(
    home_stats: CornerStats, away_stats: CornerStats, league_avg_corners: float = DEFAULT_LEAGUE_AVG_CORNERS
) -> float:
    """Estima el total de córners esperado del partido (suma de ambos equipos)."""
    home_for = _shrink(home_stats.avg_corners_home, home_stats.home_sample_size, league_avg_corners)
    away_conceded = _shrink(away_stats.avg_corners_conceded_away, away_stats.away_sample_size, league_avg_corners)
    away_for = _shrink(away_stats.avg_corners_away, away_stats.away_sample_size, league_avg_corners)
    home_conceded = _shrink(home_stats.avg_corners_conceded_home, home_stats.home_sample_size, league_avg_corners)

    home_xc = (home_for + away_conceded) / 2
    away_xc = (away_for + home_conceded) / 2
    total = home_xc + away_xc
    return min(max(total, 2.0), 20.0)


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


def total_goals_probabilities(home_xg: float, away_xg: float, line: float) -> dict:
    """P(total de goles > línea) y P(< línea), integrando la matriz de Poisson."""
    home_probs = [_poisson_pmf(i, home_xg) for i in range(MAX_GOALS + 1)]
    away_probs = [_poisson_pmf(j, away_xg) for j in range(MAX_GOALS + 1)]

    p_over = 0.0
    for i, ph in enumerate(home_probs):
        for j, pa in enumerate(away_probs):
            if i + j > line:
                p_over += ph * pa
    return {"over": p_over, "under": 1 - p_over}


def btts_probabilities(home_xg: float, away_xg: float) -> dict:
    """P(ambos marcan = Sí/No), asumiendo independencia entre goles local/visitante."""
    p_home_0 = _poisson_pmf(0, home_xg)
    p_away_0 = _poisson_pmf(0, away_xg)
    p_no = p_home_0 + p_away_0 - p_home_0 * p_away_0
    return {"yes": 1 - p_no, "no": p_no}


def total_corners_probabilities(total_corners_xg: float, line: float) -> dict:
    """P(total de córners > línea) y P(< línea), modelando el total con Poisson."""
    floor_line = int(line)  # las líneas son X.5, así que floor(line) alcanza como corte
    p_under = _poisson_cdf(floor_line, total_corners_xg)
    p_under = min(max(p_under, 0.0), 1.0)
    return {"over": 1 - p_under, "under": p_under}


def devigged_implied_probabilities(odds: dict) -> dict:
    """Quita el margen de la casa (overround) normalizando las probabilidades implícitas."""
    raw = {k: 1.0 / v for k, v in odds.items() if v}
    overround = sum(raw.values())
    return {k: v / overround for k, v in raw.items()}
