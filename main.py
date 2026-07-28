"""Detector de cuotas con valor en Codere comparando contra estadísticas de Sofascore.

Uso:
    python main.py                # corre una vez y envía email si encuentra valor
    python main.py --dry-run      # corre una vez, solo imprime resultados, no envía email
    python main.py --loop         # corre en bucle cada CHECK_INTERVAL_MINUTES minutos
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import config
from notifier import send_value_bet_alert
from value_finder import ValueBet, find_value_bets, value_bet_to_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def print_report(value_bets: list[ValueBet]) -> None:
    if not value_bets:
        print("No se detectaron cuotas con valor en esta pasada.")
        return

    print(f"\n{len(value_bets)} cuota(s) con posible error/valor:\n")
    for vb in value_bets:
        m = vb.match
        fecha = m.start_date.strftime("%d/%m %H:%M") if m.start_date else "sin fecha"
        print(
            f"- {m.home} vs {m.away} ({m.league}, {fecha})\n"
            f"    [{vb.market}] {vb.selection_label} @ {vb.codere_odd:.2f} | "
            f"modelo: {vb.model_prob*100:.1f}% vs implícita: {vb.implied_prob*100:.1f}% "
            f"(edge +{vb.edge*100:.1f} pts)"
        )
    print()


def publish_json(path: str, value_bets: list[ValueBet]) -> None:
    """Escribe un snapshot JSON con los resultados, para servir desde una web estática."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "value_bets": [value_bet_to_dict(vb) for vb in value_bets],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Resultados publicados en %s (%d cuotas con valor)", path, len(value_bets))


def run_once(dry_run: bool, publish_json_path: str | None) -> None:
    logger.info("Buscando cuotas con valor...")
    value_bets = find_value_bets()
    print_report(value_bets)
    if publish_json_path:
        publish_json(publish_json_path, value_bets)
    elif not dry_run:
        send_value_bet_alert(value_bets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No enviar email, solo mostrar resultados")
    parser.add_argument("--loop", action="store_true", help="Ejecutar en bucle periódicamente")
    parser.add_argument(
        "--publish-json",
        metavar="PATH",
        help="Escribir los resultados en un archivo JSON (para servir en una web) en vez de mandar email",
    )
    args = parser.parse_args()

    if args.loop:
        logger.info("Modo bucle: cada %d minutos (Ctrl+C para salir)", config.CHECK_INTERVAL_MINUTES)
        while True:
            try:
                run_once(args.dry_run, args.publish_json)
            except Exception:
                logger.exception("Error en la ejecución periódica")
            time.sleep(config.CHECK_INTERVAL_MINUTES * 60)
    else:
        run_once(args.dry_run, args.publish_json)


if __name__ == "__main__":
    main()
