"""Envío de alertas por email (SMTP) cuando se detectan cuotas con valor."""
import logging
import smtplib
from email.mime.text import MIMEText

import config
from value_finder import ValueBet

logger = logging.getLogger(__name__)


def _build_body(value_bets: list[ValueBet]) -> str:
    lines = [
        "Se detectaron las siguientes cuotas de Codere con valor respecto",
        "al modelo estadístico basado en datos de ESPN:",
        "",
    ]
    for vb in value_bets:
        m = vb.match
        fecha = m.start_date.strftime("%d/%m %H:%M") if m.start_date else "sin fecha"
        lines.append(
            f"- {m.home} vs {m.away} ({m.league}, {fecha})\n"
            f"  Mercado: {vb.market} | Selección: {vb.selection_label} | Cuota Codere: {vb.codere_odd:.2f}\n"
            f"  Prob. modelo: {vb.model_prob*100:.1f}% | Prob. implícita (sin margen): "
            f"{vb.implied_prob*100:.1f}% | Edge: +{vb.edge*100:.1f} pts"
        )
        lines.append("")
    lines.append(
        "Aviso: esto es una estimación estadística simple, no garantiza ganancias. "
        "Apostar implica riesgo económico y de ludopatía."
    )
    return "\n".join(lines)


def send_value_bet_alert(value_bets: list[ValueBet]) -> None:
    if not value_bets:
        logger.info("No hay cuotas con valor, no se envía email")
        return

    if not config.SMTP_USER or not config.SMTP_PASSWORD or not config.EMAIL_TO:
        logger.error(
            "Faltan credenciales SMTP (SMTP_USER/SMTP_PASSWORD/EMAIL_TO) en el archivo .env, "
            "no se puede enviar el email"
        )
        return

    subject = f"[Codere] {len(value_bets)} cuota(s) con posible error/valor detectada(s)"
    body = _build_body(value_bets)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = config.EMAIL_TO

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.REQUEST_TIMEOUT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, [config.EMAIL_TO], msg.as_string())
        logger.info("Email enviado a %s con %d cuotas con valor", config.EMAIL_TO, len(value_bets))
    except smtplib.SMTPException:
        logger.exception("Error enviando el email de alerta")
