#!/usr/bin/env python3
"""
PostToolUse-Hook: reserviert eine Datei beim ersten Zugriff.

Läuft nach jedem Edit, tut aber fast immer nichts. Nur wenn die Datei
noch nicht in der eigenen Reservierungsliste steht, wird geschrieben und
gepusht. Bei jedem weiteren Edit derselben Datei kostet der Hook einen
Dateizugriff, sonst entstünde pro Edit ein Commit, und der Channel wäre
nach einer Stunde unlesbar.

Eine Session, die zwölf Dateien anfasst, erzeugt über Stunden zwölf
kleine Pushes. Das trägt.

Läuft unter Claude Code und unter Antigravity. Welches Werkzeug eine
Datei verändert und wo in der Nutzlast der Pfad steckt, entscheidet
lib/host.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    from lib import host

    daten = host.lies_ereignis("PostToolUse")

    if not daten.ist_edit():
        host.fertig(daten.host)
        return

    from lib.channel import (
        datei_merken,
        get_project_dir,
        schneller_kontext,
        setup_stdio,
    )
    from lib import reservierung

    setup_stdio()

    project_dir = get_project_dir()
    kontext = schneller_kontext(project_dir)
    if not kontext:
        host.fertig(daten.host)
        return

    channel_dir = Path(kontext.get("channel", ""))
    try:
        if not (channel_dir / reservierung.ORDNER).is_dir():
            host.fertig(daten.host)
            return
    except Exception:
        host.fertig(daten.host)
        return

    ich = kontext.get("person", "")
    datei = reservierung.normalisiere(daten.datei, project_dir)

    # Zweitverwertung: Die Liste der angefassten Dateien entsteht hier
    # nebenbei. Der automatische Status zieht sie heran, wenn das
    # Transkript nichts hergibt, und genau das ist unter Antigravity der
    # Regelfall. Steht vor der Prüfung unten, damit auch eine Datei
    # mitgezählt wird, deren Reservierung schon länger steht.
    datei_merken(project_dir, datei)

    # Der häufige Fall: schon reserviert, nichts zu tun. Diese Prüfung
    # liest eine kleine Datei und ist damit billig genug, um sie bei
    # jedem Edit zu machen.
    if reservierung.habe_ich_schon(channel_dir, ich, datei):
        host.fertig(daten.host)
        return

    reservierung.reservieren(
        channel_dir,
        ich,
        kontext.get("branch", ""),
        daten.session,
        datei,
    )

    host.fertig(daten.host)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
