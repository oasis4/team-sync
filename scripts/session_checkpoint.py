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

from lib import empfang
from lib.autostatus import schreibe_status
from lib.channel import (
    channel_is_ready,
    get_agent_name,
    get_channel_dir,
    get_project_dir,
    pull_channel,
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


def empfangen(project_dir) -> str:
    """
    Holt den aktuellen Stand und meldet, was für diese Session neu ist.

    Läuft in einem eigenen, kürzeren Takt als das Schreiben. Lesen ist
    billig, und die Wartezeit auf eine Antwort ist genau das, was hier
    verkürzt werden soll: Ohne diesen Teil erfährt eine stundenlang
    laufende Session erst beim nächsten Start, dass ihre Frage längst
    beantwortet wurde.
    """
    if not empfang.faellig(project_dir):
        return ""

    channel_dir = get_channel_dir(project_dir)
    if not channel_is_ready(channel_dir):
        return ""

    pull_channel(channel_dir, timeout=15)
    return empfang.neuigkeiten(channel_dir, project_dir, get_agent_name(project_dir))


def main():
    setup_stdio()
    hook_input = read_hook_input()
    nachricht = ""

    try:
        project_dir = get_project_dir()

        nachricht = empfangen(project_dir)

        erzwungen = os.environ.get("TEAM_SYNC_FORCE") == "1"
        if erzwungen or should_checkpoint(project_dir, MIN_INTERVAL_SECONDS):
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
