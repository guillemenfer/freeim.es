"""Detector de cuotas con valor y eventos probables en Codere, comparando contra
estadísticas de ESPN.

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


def _print_bets(title: str, bets: list[ValueBet], show_edge: bool) -> None:
    if not bets:
        print(f"{title}: ninguno en esta pasada.")
        return
    print(f"\n{title} ({len(bets)}):\n")
    for vb in bets:
        m = vb.match
        fecha = m.start_date.strftime("%d/%m %H:%M") if m.start_date else "sin fecha"
        extra = f" (edge +{vb.edge*100:.1f} pts)" if show_edge else ""
        print(
            f"- {m.home} vs {m.away} ({m.league}, {fecha})\n"
            f"    [{vb.market}] {vb.selection_label} @ {vb.codere_odd:.2f} | "
            f"modelo: {vb.model_prob*100:.1f}% vs implícita: {vb.implied_prob*100:.1f}%{extra}"
        )
    print()


def print_report(value_bets: list[ValueBet], likely_events: list[ValueBet]) -> None:
    _print_bets("Cuotas con valor", value_bets, show_edge=True)
    _print_bets("Eventos probables", likely_events, show_edge=False)


def publish_json(path: str, value_bets: list[ValueBet], likely_events: list[ValueBet]) -> None:
    """Escribe un snapshot JSON con los resultados, para servir desde una web estática."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "value_bets": [value_bet_to_dict(vb) for vb in value_bets],
        "likely_events": [value_bet_to_dict(vb) for vb in likely_events],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(
        "Resultados publicados en %s (%d cuotas con valor, %d eventos probables)",
        path, len(value_bets), len(likely_events),
    )


def run_once(dry_run: bool, publish_json_path: str | None) -> None:
    logger.info("Buscando cuotas con valor y eventos probables...")
    value_bets, likely_events, stats = find_value_bets()

    if stats.looks_blocked:
        print(
            f"ESPN pareció bloquear esta corrida ({stats.teams_resolved}/{stats.teams_attempted} "
            "equipos resueltos). No se publican ni envían resultados esta vez."
        )
        return

    print_report(value_bets, likely_events)
    if publish_json_path:
        publish_json(publish_json_path, value_bets, likely_events)
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
