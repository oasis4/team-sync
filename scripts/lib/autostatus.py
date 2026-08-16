"""
Der automatisch geschriebene Status.

Gemeinsame Logik der beiden Hooks, die ungefragt schreiben: der
Zwischenstand während einer laufenden Session (Stop) und der finale
Status beim Beenden (SessionEnd). Beide erzeugen dieselbe Datei, sie
unterscheiden sich nur im Anlass.
"""

from .channel import (
    channel_is_ready,
    get_agent_name,
    get_channel_dir,
    get_current_branch,
    get_project_dir,
    now_stamp,
    write_and_push,
)
from .render import render_status
from .transcript import summarize


def schreibe_status(transcript_path, quelle, anlass=""):
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

    inhalt = render_status(
        person=me,
        branch=branch,
        stamp=stamp,
        quelle=quelle,
        auftrag=zusammenfassung["auftrag"],
        zuletzt=zusammenfassung["zuletzt"],
        dateien=zusammenfassung["dateien"],
    )

    nachricht = f"status: {me} - {stamp}"
    if anlass:
        nachricht += f" ({anlass})"

    write_and_push(channel_dir, f"status/{me}.md", inhalt, nachricht)
    return True
