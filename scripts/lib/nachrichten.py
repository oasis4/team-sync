"""
Nachrichten: kurze Mitteilungen an bestimmte Teammitglieder.

Die Idee stammt vom Hackathon-Board (github.com/azizu06/hackathon-agent-board).
Dort posten die Agenten aller Teammitglieder in ein gemeinsames GitHub-Issue
und markieren sich gegenseitig mit @name. So kann ein Agent dem Agenten
eines anderen Arbeit übergeben, ohne dass zwei Menschen sich schreiben.

Was hier anders ist: Es gibt keinen Thread, sondern eine Datei pro
Nachricht, wie bei allem anderen im Channel. Damit gibt es keine
Merge-Konflikte, und der Kanal hängt weder an GitHub noch an der gh-CLI.
Und gemeldet wird nur, was an einen selbst oder an alle geht. Das Board
lässt jeden Agenten jeden Beitrag lesen, was bei tausend Beiträgen an
einem Wochenende in jeder Session Tokens kostet, die niemandem helfen.

Wofür Nachrichten gedacht sind, und wofür nicht:

    Übergaben      "Login ist gemergt, @max kann die API-Route bauen"
    Änderungen     "@alle Die Umgebungsvariable DB_URL heißt jetzt DATABASE_URL"
    Blocker        "@lars ich brauche das Schema für orders, bevor ich weiterkomme"

Eine Frage, die eine Antwort braucht, gehört nach questions/, eine
Festlegung nach decisions/. Eine Nachricht ist dafür da, dass jemand
etwas weiß, nicht für ein Gespräch.

    ---
    typ: nachricht
    von: lars
    an: max-mustermann
    erstellt: 2026-11-02 14:32
    branch: feature/login
    ---

    Login ist gemergt, @max kann die API-Route bauen.
"""

import os
import re
from pathlib import Path

from . import frontmatter
from .channel import (
    channel_is_ready,
    list_files_sorted,
    now_id,
    now_stamp,
    read_text,
    slugify,
    write_and_push,
)

ORDNER = "nachrichten"
TYP = "nachricht"

# Wie viele Nachrichten höchstens in den Sessionstart-Kontext kommen.
MAX_IM_KONTEXT = int(os.environ.get("TEAM_SYNC_MAX_NACHRICHTEN", "5"))

# @name, aber nicht in einer Mailadresse wie max@example.com. Erlaubt
# sind Buchstaben mit Umlauten, Ziffern, Punkt, Bindestrich und
# Unterstrich, ein abschließender Punkt gehört zum Satz, nicht zum Namen.
_ERWAEHNUNG = re.compile(r"(?<![\w@.])@([^\W_][\w.-]*)", re.UNICODE)


def erwaehnungen(text: str):
    """Alle @namen im Text, in Reihenfolge, ohne Doppelte."""
    gesehen = []
    for treffer in _ERWAEHNUNG.finditer(text or ""):
        name = treffer.group(1).rstrip(".-")
        if name and name.lower() not in [g.lower() for g in gesehen]:
            gesehen.append(name)
    return gesehen


def lesen(pfad: Path):
    felder, rumpf = frontmatter.parse(read_text(pfad))
    return {
        "id": pfad.stem,
        "von": frontmatter.get(felder, "von"),
        "an": frontmatter.get(felder, "an"),
        "erstellt": frontmatter.get(felder, "erstellt"),
        "branch": frontmatter.get(felder, "branch"),
        "text": rumpf.strip(),
        "path": pfad,
    }


def alle(channel_dir: Path):
    """Alle Nachrichten, älteste zuerst."""
    return [lesen(pfad) for pfad in list_files_sorted(channel_dir / ORDNER)]


def ist_an_alle(eintrag) -> bool:
    return any(
        slugify(teil) in frontmatter.ALLE_SYNONYME
        for teil in (eintrag["an"] or "").split(",")
    )


def an_mich(channel_dir: Path, me: str):
    """
    Nachrichten an mich oder an alle, ohne meine eigenen.

    Die eigenen fallen heraus, auch wenn sie an alle gingen. Wer etwas
    an alle schreibt, braucht es nicht zurückgemeldet zu bekommen.
    """
    eigener = slugify(me)
    return [
        eintrag
        for eintrag in alle(channel_dir)
        if slugify(eintrag["von"] or "") != eigener
        and frontmatter.matches_person(eintrag["an"], me, alle=True)
    ]


def schreiben(channel_dir: Path, von: str, an, branch: str, text: str):
    """
    Legt eine Nachricht an und pusht sie.

    an ist eine Liste aufgelöster Slugs, oder ["alle"]. Rückgabe ist
    (relativer Pfad, gepusht), der Pfad ist leer, wenn nichts
    geschrieben werden konnte.
    """
    if not channel_is_ready(channel_dir):
        return "", False

    empfaenger = ", ".join(an) if an else frontmatter.ALLE

    # Ein Agent schreibt durchaus zwei Nachrichten in derselben Sekunde.
    # Ohne Zähler würde die zweite die erste überschreiben.
    stamm = f"{now_id()}-{slugify(von)}"
    dateiname = f"{stamm}.md"
    zaehler = 2
    while (channel_dir / ORDNER / dateiname).exists():
        dateiname = f"{stamm}-{zaehler}.md"
        zaehler += 1
    relativ = f"{ORDNER}/{dateiname}"

    inhalt = frontmatter.build(
        {
            "typ": TYP,
            "von": slugify(von),
            "an": empfaenger,
            "erstellt": now_stamp(),
            "branch": branch,
        },
        text.strip() + "\n",
    )

    kurz = " ".join(text.split())[:50]
    gepusht = write_and_push(
        channel_dir, relativ, inhalt, f"nachricht: {slugify(von)} an {empfaenger} - {kurz}"
    )
    return relativ, gepusht
