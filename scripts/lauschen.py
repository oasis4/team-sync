#!/usr/bin/env python3
"""
Plugin-Monitor: meldet Neues aus dem Team-Channel, solange die Session läuft.

Eingetragen in monitors/monitors.json. Claude Code startet das Skript
mit jeder Session im Hintergrund und beendet es mit ihr. Jede Ausgabe
kommt bei Claude als Benachrichtigung an, auch wenn die Session gerade
auf Eingabe wartet. Damit kann der Agent einer anderen Person diese
Session erreichen, etwa mit einer Übergabe oder einer Frage.

Aufruf, wie ihn monitors.json einträgt:

    python3 lauschen.py [projektordner]

Ohne Channel im Projekt, oder mit TEAM_SYNC_LAUSCHEN=aus, tut das Skript
nichts und wartet nur auf das Ende der Session. Warum es sich dann nicht
einfach beendet, steht in lib/lauschen.py bei ruhen().

Die Logik steckt in lib/lauschen.py, damit 'team_sync.py warten'
dieselbe Schleife benutzt.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import lauschen
from lib.channel import get_channel_dir, get_project_dir, run_git, setup_stdio


def projektordner() -> Path:
    """
    Der Projektordner, aus dem Argument oder aus der Umgebung.

    Claude Code ersetzt ${CLAUDE_PROJECT_DIR} im Monitorbefehl. Tut es
    das nicht, kommt ein leeres Argument an, und dann gilt das aktuelle
    Verzeichnis. Der Monitor startet im Arbeitsordner der Session, kann
    dort aber in einem Unterordner stehen, deshalb geht es über git auf
    die oberste Ebene.
    """
    if len(sys.argv) > 1 and sys.argv[1].strip() and "${" not in sys.argv[1]:
        os.environ.setdefault("TEAM_SYNC_PROJECT_DIR", sys.argv[1].strip())

    kandidat = get_project_dir()
    ok, oben = run_git(["rev-parse", "--show-toplevel"], cwd=kandidat)
    return Path(oben).resolve() if ok and oben else kandidat


def main() -> int:
    setup_stdio()

    if lauschen.abgeschaltet():
        return lauschen.ruhen()

    project_dir = projektordner()
    channel_dir = get_channel_dir(project_dir)
    if not lauschen.bereit(channel_dir):
        return lauschen.ruhen()

    return lauschen.schleife(
        project_dir,
        channel_dir,
        startverzoegerung=lauschen.STARTVERZOEGERUNG,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
