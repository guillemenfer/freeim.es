"""Configuración centralizada, cargada desde variables de entorno (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Codere ---
CODERE_EVENTS_URL = "https://m.apuestas.codere.es/NavigationService/Event/GetEvents"
# GameTypeId de Codere para cada mercado (ver codere_client.py)
CODERE_MARKET_1X2 = 1
CODERE_MARKET_TOTAL_GOALS = 18
CODERE_MARKET_BTTS = 31
CODERE_MARKET_CORNERS = 54
# NodeId de liga en Codere -> nombre (debe coincidir con el LeagueName que devuelve
# Codere). Se pide el fixture completo de cada una (no solo lo "destacado" en portada).
_DEFAULT_LEAGUES = (
    "3253425078:Liga Profesional,3788530433:Eliteserien,2995719538:Allsvenskan,"
    "2995723493:Veikkausliiga"
)
CODERE_LEAGUE_NODE_IDS = {
    nid.strip(): name.strip()
    for pair in os.getenv("CODERE_LEAGUE_NODE_IDS", _DEFAULT_LEAGUES).split(",")
    for nid, name in [pair.split(":", 1)]
    if pair.strip()
}

# --- Fuentes de estadísticas ---
# Nombre de liga (igual que arriba) -> proveedor de estadísticas ("espn" o "flashscore").
# ESPN no tiene datos reales para todas las ligas (ej. Veikkausliiga de Finlandia le
# devuelve una temporada vacía/desactualizada); para esas se usa Flashscore en cambio.
_DEFAULT_STATS_PROVIDERS = (
    "Liga Profesional:espn,Eliteserien:espn,Allsvenskan:espn,Veikkausliiga:flashscore"
)
STATS_PROVIDERS = {
    name.strip(): provider.strip()
    for pair in os.getenv("STATS_PROVIDERS", _DEFAULT_STATS_PROVIDERS).split(",")
    for name, provider in [pair.split(":", 1)]
    if pair.strip()
}
# Nombre de liga -> slug de liga de ESPN (soccer), para las que usan proveedor "espn".
_DEFAULT_ESPN_SLUGS = "Liga Profesional:arg.1,Eliteserien:nor.1,Allsvenskan:swe.1"
ESPN_LEAGUE_SLUGS = {
    name.strip(): slug.strip()
    for pair in os.getenv("ESPN_LEAGUE_SLUGS", _DEFAULT_ESPN_SLUGS).split(",")
    for name, slug in [pair.split(":", 1)]
    if pair.strip()
}
# Nombre de liga -> "tournamentId:tournamentStageId" de Flashscore, para las que usan
# proveedor "flashscore". Se ubican inspeccionando las llamadas de red que hace
# flashscore.com a "2.flashscore.ninja/2/x/feed/to_<tournamentId>_<stageId>_1".
_DEFAULT_FLASHSCORE_TOURNAMENTS = "Veikkausliiga:jg5JgLZo:h6IND07k"
FLASHSCORE_TOURNAMENTS = {
    name.strip(): f"{tid.strip()}:{stage.strip()}"
    for entry in os.getenv("FLASHSCORE_TOURNAMENTS", _DEFAULT_FLASHSCORE_TOURNAMENTS).split(",")
    for name, tid, stage in [entry.split(":", 2)]
    if entry.strip()
}
FORM_MATCHES = int(os.getenv("FORM_MATCHES", "8"))  # partidos recientes usados para el modelo
LEAGUE_AVG_CORNERS = float(os.getenv("LEAGUE_AVG_CORNERS", "5.0"))  # córners promedio de un equipo por partido

# --- Red / cortesía con los servidores ---
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "0.8"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)

# --- Modelo de valor ---
# Diferencia mínima (probabilidad del modelo - probabilidad implícita sin margen)
# para considerar que una cuota tiene "valor" / está mal calculada.
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.05"))
# Edges por encima de esto casi seguro son error del modelo (falta de contexto sobre nivel
# real del equipo), no una cuota mal puesta de verdad, así que se descartan en vez de avisar.
MAX_TRUSTED_EDGE = float(os.getenv("MAX_TRUSTED_EDGE", "0.15"))
# Selecciones con probabilidad del modelo por encima de esto se listan aparte como
# "eventos probables", independientemente de si la cuota tiene valor (edge) o no.
HIGH_PROB_THRESHOLD = float(os.getenv("HIGH_PROB_THRESHOLD", "0.65"))
NAME_MATCH_THRESHOLD = float(os.getenv("NAME_MATCH_THRESHOLD", "0.6"))

# --- Email (SMTP) ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", SMTP_USER)

# --- Ejecución periódica ---
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))
