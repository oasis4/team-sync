"""
Dateianfragen: die Klärung zwischen zwei Sessions.

Stößt eine Session auf eine reservierte Datei, legt sie hier eine
Anfrage ab und arbeitet sofort weiter. Die andere Session sieht sie in
ihrem Kontext und antwortet — oft genauer, als ein Mensch es könnte,
weil Claude dort tatsächlich weiß, an welcher Stelle es gerade
arbeitet.

Technisch sind das normale Einträge in questions/, mit zwei
Unterschieden: Sie tragen einen Dateibezug, und sie werden in Minuten
beantwortet statt in Stunden. Bleibt die Antwort aus, gilt nach kurzer
Frist: einfach machen. Eine Session, deren Gegenüber längst geschlossen
ist, darf nicht ewig auf eine Antwort warten.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from . import frontmatter
from .channel import (
    channel_is_ready,
    get_git_dir,
    list_files_sorted,
    now_id,
    now_stamp,
    parse_stamp,
    read_text,
    slugify,
    write_and_push,
)

# Wie lange auf eine Antwort gewartet wird, bevor die Reservierung als
# geklärt gilt und weitergearbeitet werden darf.
TIMEOUT_MINUTEN = int(os.environ.get("TEAM_SYNC_ANFRAGE_TIMEOUT", "10"))

# Wie lange nach einer Anfrage zu derselben Datei nicht erneut gefragt
# wird — auch dann nicht, wenn die erste unbeantwortet blieb.
SPERRE_MINUTEN = int(os.environ.get("TEAM_SYNC_ANFRAGE_SPERRE", "60"))

TYP = "dateianfrage"


def _lesen(pfad: Path):
    felder, rumpf = frontmatter.parse(read_text(pfad))
    return {
        "id": pfad.stem,
        "typ": frontmatter.get(felder, "typ"),
        "von": frontmatter.get(felder, "von"),
        "an": frontmatter.get(felder, "an"),
        "datei": frontmatter.get(felder, "datei"),
        "erstellt": frontmatter.get(felder, "erstellt"),
        "status": frontmatter.get(felder, "status", "offen").lower(),
        "branch": frontmatter.get(felder, "branch"),
        "titel": frontmatter.get(felder, "titel"),
        "body": rumpf.strip(),
        "path": pfad,
    }


def nur_antwort(body: str) -> str:
    """
    Schneidet aus einer beantworteten Anfrage den Antwortteil heraus.

    Die eigene Frage noch einmal vorgelegt zu bekommen, hilft niemandem
    und kostet in jeder Meldung Tokens. Interessant ist, was zurückkam.
    """
    marke = "## Antwort"
    stelle = body.find(marke)
    if stelle == -1:
        return body.strip()
    rest = body[stelle + len(marke):]
    # Die Klammer mit Person und Zeitstempel steht in derselben Zeile.
    kopfende = rest.find("\n")
    return rest[kopfende + 1:].strip() if kopfende != -1 else rest.strip()


def alle(channel_dir: Path):
    ergebnis = []
    for pfad in list_files_sorted(channel_dir / "questions"):
        eintrag = _lesen(pfad)
        if eintrag["typ"] == TYP:
            ergebnis.append(eintrag)
    return ergebnis


def fuer_datei(channel_dir: Path, datei: str):
    """Alle Anfragen zu einer bestimmten Datei, neueste zuletzt."""
    gesucht = (datei or "").lower()
    return [a for a in alle(channel_dir) if (a["datei"] or "").lower() == gesucht]


def ist_verfallen(eintrag) -> bool:
    """
    Blieb die Anfrage lange genug unbeantwortet, um sie aufzugeben?

    Der Sinn ist nicht Ungeduld, sondern dass die Gegenseite eine tote
    Session sein kann: Rechner zu, niemand da, der je antworten wird.
    """
    if eintrag["status"] != "offen":
        return False
    zeitpunkt = parse_stamp(eintrag["erstellt"])
    if zeitpunkt is None:
        return True
    return datetime.now() - zeitpunkt > timedelta(minutes=TIMEOUT_MINUTEN)


def offen_und_wartend(channel_dir: Path, datei: str):
    """
    Läuft zu dieser Datei gerade eine Anfrage, auf die noch sinnvoll
    gewartet wird? Verfallene zählen nicht mehr.
    """
    for eintrag in fuer_datei(channel_dir, datei):
        if eintrag["status"] == "offen" and not ist_verfallen(eintrag):
            return eintrag
    return None


def beantwortet_kuerzlich(channel_dir: Path, datei: str):
    for eintrag in reversed(fuer_datei(channel_dir, datei)):
        if eintrag["status"] != "offen":
            return eintrag
    return None


def stellen(channel_dir: Path, von: str, an: str, datei: str, branch: str,
            text: str) -> str:
    """
    Legt eine Anfrage an und pusht sie. Gibt die id zurück, oder "".
    """
    if not channel_is_ready(channel_dir) or not datei:
        return ""

    titel = f"Zugriff auf {datei}"
    dateiname = f"{now_id()}-{slugify(von)}-anfrage-{slugify(datei)[:40]}.md"

    inhalt = frontmatter.build(
        {
            "typ": TYP,
            "von": slugify(von),
            "an": slugify(an),
            "datei": datei,
            "erstellt": now_stamp(),
            "branch": branch,
            "status": "offen",
            "titel": titel,
        },
        f"# {titel}\n\n{text.strip()}\n",
    )

    # Auch ein fehlgeschlagener Push ist kein Grund, die id zu
    # verschweigen: Die Datei liegt dann lokal und der nächste Sync
    # schiebt sie nach.
    write_and_push(
        channel_dir,
        f"questions/{dateiname}",
        inhalt,
        f"anfrage: {slugify(von)} an {slugify(an)} - {datei}",
    )
    return dateiname[:-len(".md")]


# ---------------------------------------------------------------------------
# Drosselung
# ---------------------------------------------------------------------------


def _marker_pfad(project_dir: Path):
    git_dir = get_git_dir(project_dir)
    return (git_dir / "team-sync-anfragen.json") if git_dir else None


def _marker_laden(project_dir: Path):
    pfad = _marker_pfad(project_dir)
    if pfad is None or not pfad.exists():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except Exception:
        return {}


def schon_gefragt(project_dir: Path, datei: str) -> bool:
    """
    Wurde zu dieser Datei kürzlich schon gefragt?

    Ohne diese Sperre entstünde bei jedem weiteren Edit eine neue
    Anfrage, und der Channel wäre nach einer Stunde unbrauchbar.

    Die Sperre hängt an der Zeit, nicht an einer Sitzungskennung. Der
    erste Entwurf tat Letzteres, und die Sperre griff nie: Der Hook
    kennt die Kennung aus seiner Payload, das Kommandozeilenwerkzeug
    kennt sie nicht. Zwei verschiedene Schlüssel, ein wirkungsloser
    Riegel — und im Alltag eine Anfrage pro Edit.
    """
    stempel = _marker_laden(project_dir).get(datei)
    zeitpunkt = parse_stamp(stempel) if stempel else None
    if zeitpunkt is None:
        return False
    return datetime.now() - zeitpunkt < timedelta(minutes=SPERRE_MINUTEN)


def merke_gefragt(project_dir: Path, datei: str):
    pfad = _marker_pfad(project_dir)
    if pfad is None:
        return
    try:
        daten = _marker_laden(project_dir)
        daten[datei] = now_stamp()
        pfad.write_text(json.dumps(daten), encoding="utf-8")
    except Exception:
        pass
