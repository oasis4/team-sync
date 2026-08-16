#!/usr/bin/env python3
"""
Stop-Hook: schreibt gedrosselt einen Zwischenstand.

Läuft nach jeder Antwort von Claude, tut aber fast immer nichts. Nur
wenn seit dem letzten Zwischenstand genug Zeit vergangen ist
(Vorgabe zehn Minuten, TEAM_SYNC_CHECKPOINT_SECONDS), wird der eigene
Status neu geschrieben und gepusht.

Warum es diesen Hook überhaupt gibt: SessionEnd feuert erst, wenn eine
Session wirklich endet. Wer morgens eine Session öffnet und sie bis
abends offenlässt, taucht im Channel den ganzen Tag über mit dem Stand
von gestern auf. Für ein Werkzeug, dessen einziger Zweck es ist, dass
das Team weiß was gerade läuft, wäre das der entscheidende Fehler.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.autostatus import schreibe_status
from lib.channel import (
    get_project_dir,
    setup_stdio,
    should_checkpoint,
    touch_throttle,
)

MIN_INTERVAL_SECONDS = int(os.environ.get("TEAM_SYNC_CHECKPOINT_SECONDS", "600"))


def read_hook_input():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def main():
    setup_stdio()
    hook_input = read_hook_input()

    try:
        project_dir = get_project_dir()

        erzwungen = os.environ.get("TEAM_SYNC_FORCE") == "1"
        if not erzwungen and not should_checkpoint(project_dir, MIN_INTERVAL_SECONDS):
            return

        geschrieben = schreibe_status(
            hook_input.get("transcript_path", ""),
            quelle="zwischenstand",
            anlass="automatisch",
        )

        # Marker nur setzen, wenn wirklich geschrieben wurde. Sonst
        # würde ein Projekt ohne Channel die Drosselung stumm
        # weiterlaufen lassen und der erste Zwischenstand nach dem
        # Einrichten käme mit zehn Minuten Verspätung.
        if geschrieben:
            touch_throttle(project_dir)
    except Exception as exc:
        print(f"team-sync: Zwischenstand fehlgeschlagen: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
