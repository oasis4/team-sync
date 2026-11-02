#!/usr/bin/env python3
"""
UserPromptSubmit-Hook: Neues aus dem Channel, bevor das Modell antwortet.

Das Hackathon-Board zeigt ungelesene Beiträge bei jeder Eingabe an, und
das ist der Moment, in dem eine Meldung am meisten nützt: Der Mensch
ist gerade da, und das Modell plant gleich den nächsten Schritt. Bis 0.4
kam der Rückkanal nur nach einer Antwort von Claude, also einen Zug zu
spät.

Dieser Hook läuft vor jeder Eingabe, deshalb gilt hier dieselbe Regel
wie vor jedem Edit:

    Kein Netzwerkzugriff. Gelesen wird der lokale Stand.

Aktuell hält den der Lauscher im Hintergrund, und ohne Lauscher der
Stop-Hook. Ein Pull an dieser Stelle hieße, dass jede Eingabe bei
schlechtem Netz sekundenlang hängt, und genau das würde jeder bemerken.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass

    from lib.channel import get_project_dir, schneller_kontext, setup_stdio

    setup_stdio()

    project_dir = get_project_dir()
    kontext = schneller_kontext(project_dir)
    if not kontext:
        return

    channel_dir = Path(kontext.get("channel", ""))
    try:
        if not (channel_dir / "status").is_dir():
            return
    except Exception:
        return

    from lib import empfang

    text = empfang.neuigkeiten(channel_dir, project_dir, kontext.get("person", ""))
    if not text:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ein Fehler hier darf nie eine Eingabe verhindern.
        pass
