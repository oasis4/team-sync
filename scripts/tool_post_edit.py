#!/usr/bin/env python3
"""
PostToolUse-Hook: reserviert eine Datei beim ersten Zugriff.

Läuft nach jedem Edit, tut aber fast immer nichts. Nur wenn die Datei
noch nicht in der eigenen Reservierungsliste steht, wird geschrieben und
gepusht. Bei jedem weiteren Edit derselben Datei kostet der Hook einen
Dateizugriff — sonst entstünde pro Edit ein Commit, und der Channel wäre
nach einer Stunde unlesbar.

Eine Session, die zwölf Dateien anfasst, erzeugt über Stunden zwölf
kleine Pushes. Das trägt.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RELEVANTE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def main():
    try:
        roh = sys.stdin.read()
        payload = json.loads(roh) if roh else {}
    except Exception:
        return

    if payload.get("tool_name") not in RELEVANTE_TOOLS:
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    ziel = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not ziel:
        return

    from lib.channel import get_project_dir, schneller_kontext, setup_stdio
    from lib import reservierung

    setup_stdio()

    project_dir = get_project_dir()
    kontext = schneller_kontext(project_dir)
    if not kontext:
        return

    channel_dir = Path(kontext.get("channel", ""))
    try:
        if not (channel_dir / reservierung.ORDNER).is_dir():
            return
    except Exception:
        return

    ich = kontext.get("person", "")
    datei = reservierung.normalisiere(ziel, project_dir)

    # Der häufige Fall: schon reserviert, nichts zu tun. Diese Prüfung
    # liest eine kleine Datei und ist damit billig genug, um sie bei
    # jedem Edit zu machen.
    if reservierung.habe_ich_schon(channel_dir, ich, datei):
        return

    reservierung.reservieren(
        channel_dir,
        ich,
        kontext.get("branch", ""),
        payload.get("session_id", ""),
        datei,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
