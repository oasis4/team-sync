#!/usr/bin/env python3
"""
Stop-Hook: Rückkanal und gedrosselter Zwischenstand.

Läuft nach jeder Antwort von Claude. Zwei Aufgaben, die seit 0.5 als
zwei getrennte Hooks eingetragen sind, weil sie verschieden laufen
müssen:

    empfang     synchron. Meldet, was im Channel neu ist. Nur ein
                synchroner Hook kann Text an Claude zurückgeben.
    schreiben   im Hintergrund (async in hooks.json). Schreibt alle zehn
                Minuten den eigenen Status und pusht ihn. Ein Push kann
                Sekunden dauern, und darauf soll niemand warten.

Ohne Argument tut das Skript beides nacheinander, wie bis 0.4.

Warum es den Zwischenstand überhaupt gibt: SessionEnd feuert erst, wenn
eine Session wirklich endet. Wer morgens eine Session öffnet und sie bis
abends offenlässt, taucht im Channel den ganzen Tag über mit dem Stand
von gestern auf.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import empfang
from lib.autostatus import schreibe_status
from lib.host import CLAUDE, LABELS
from lib.channel import (
    channel_is_ready,
    get_agent_name,
    get_channel_dir,
    get_project_dir,
    lauscher_aktiv,
    pull_gesperrt,
    pull_merken,
    setup_stdio,
    should_checkpoint,
    touch_throttle,
)
from lib.lauschen import INTERVALL as LAUSCH_INTERVALL

MIN_INTERVAL_SECONDS = int(os.environ.get("TEAM_SYNC_CHECKPOINT_SECONDS", "600"))


def read_hook_input():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def empfangen(project_dir) -> str:
    """
    Meldet, was für diese Session neu ist.

    Gezogen wird hier nur, wenn kein Lauscher läuft und der letzte Pull
    lange genug her ist. Läuft ein Lauscher, hält der den Stand aktuell,
    und gelesen wird nur lokal. Das kostet keine Netzwerkzeit nach jeder
    Antwort.
    """
    channel_dir = get_channel_dir(project_dir)
    if not channel_is_ready(channel_dir):
        return ""

    if empfang.faellig(project_dir) and not lauscher_aktiv(project_dir, LAUSCH_INTERVALL):
        if pull_gesperrt(channel_dir, timeout=15, warten=3.0):
            pull_merken(project_dir)

    return empfang.neuigkeiten(channel_dir, project_dir, get_agent_name(project_dir))


def schreiben(project_dir, hook_input):
    erzwungen = os.environ.get("TEAM_SYNC_FORCE") == "1"
    if not (erzwungen or should_checkpoint(project_dir, MIN_INTERVAL_SECONDS)):
        return

    geschrieben = schreibe_status(
        hook_input.get("transcript_path", ""),
        quelle="zwischenstand",
        anlass="automatisch",
        werkzeug=LABELS[CLAUDE],
    )

    # Marker nur setzen, wenn wirklich geschrieben wurde. Sonst würde ein
    # Projekt ohne Channel die Drosselung stumm weiterlaufen lassen und
    # der erste Zwischenstand nach dem Einrichten käme mit zehn Minuten
    # Verspätung.
    if geschrieben:
        touch_throttle(project_dir)


def main():
    setup_stdio()
    modus = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "beides"
    hook_input = read_hook_input()
    nachricht = ""

    try:
        project_dir = get_project_dir()

        if modus in ("empfang", "beides"):
            nachricht = empfangen(project_dir)

        if modus in ("schreiben", "beides"):
            schreiben(project_dir, hook_input)
    except Exception as exc:
        print(f"team-sync: Stop-Hook ({modus}) fehlgeschlagen: {exc}", file=sys.stderr)

    if nachricht:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "Stop",
                        "additionalContext": nachricht,
                    }
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
