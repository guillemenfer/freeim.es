"""Configuración centralizada, cargada desde variables de entorno (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Codere ---
CODERE_HOME_INFO_URL = "https://m.apuestas.codere.es/NavigationService/Home/GetHomeInfo"
CODERE_HIGHLIGHTS_COUNT = int(os.getenv("CODERE_HIGHLIGHTS_COUNT", "60"))

# --- Sofascore ---
SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"
FORM_MATCHES = int(os.getenv("FORM_MATCHES", "8"))  # partidos recientes usados para el modelo

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
NAME_MATCH_THRESHOLD = float(os.getenv("NAME_MATCH_THRESHOLD", "0.6"))

# --- Email (SMTP) ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", SMTP_USER)

# --- Ejecución periódica ---
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))
