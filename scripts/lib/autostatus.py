"""
Der automatisch geschriebene Status.

Gemeinsame Logik der Hooks, die ungefragt schreiben: der Zwischenstand
während einer laufenden Sitzung und der finale Status beim Beenden.
Beide erzeugen dieselbe Datei, sie unterscheiden sich nur im Anlass.

Unter Claude Code hängen diese Hooks an Stop und SessionEnd, unter
Antigravity an PostInvocation und Stop. Was sie schreiben, ist
identisch, sonst könnte der Channel nicht von beiden Seiten gelesen
werden.
"""

from .channel import (
    channel_is_ready,
    gemerkte_dateien,
    get_agent_name,
    get_channel_dir,
    get_current_branch,
    get_project_dir,
    now_stamp,
    write_and_push,
)
from .render import render_status
from .transcript import summarize


def schreibe_status(transcript_path, quelle, anlass="", werkzeug=""):
    """
    Schreibt den eigenen Status in den Channel.

    Gibt True zurück, wenn geschrieben wurde, False, wenn es nichts zu
    tun gab oder der Channel fehlt. Wirft nie, denn der Aufrufer ist
    immer ein Hook.
    """
    project_dir = get_project_dir()
    channel_dir = get_channel_dir(project_dir)

    if not channel_is_ready(channel_dir):
        return False

    me = get_agent_name(project_dir)
    branch = get_current_branch(project_dir)
    zusammenfassung = summarize(transcript_path, project_dir)
    stamp = now_stamp()

    # Zwei Quellen für die Dateiliste, in dieser Reihenfolge: das
    # Transkript, weil es auch Dateien kennt, die vor dem Einrichten des
    # Channels angefasst wurden, und sonst die eigene Mitschrift aus den
    # Hooks. Die zweite hängt an keinem fremden Format und trägt den
    # Status auch dann, wenn das Transkript unbekannt aufgebaut ist.
    dateien = zusammenfassung["dateien"] or gemerkte_dateien(project_dir)

    inhalt = render_status(
        person=me,
        branch=branch,
        stamp=stamp,
        quelle=quelle,
        auftrag=zusammenfassung["auftrag"],
        zuletzt=zusammenfassung["zuletzt"],
        dateien=dateien,
        werkzeug=werkzeug,
    )

    nachricht = f"status: {me} - {stamp}"
    if anlass:
        nachricht += f" ({anlass})"

    write_and_push(channel_dir, f"status/{me}.md", inhalt, nachricht)
    return True
