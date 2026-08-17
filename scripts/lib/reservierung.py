"""
Reservierungen: wer sitzt gerade an welcher Datei.

Der Unterschied zum Status ist klein im Text und groß im Verhalten. Der
Status meldet Vergangenes ("Max hat diese Dateien angefasst") und ist bis
zu zehn Minuten alt. Eine Reservierung meldet Gegenwärtiges ("ich bin an
auth.py dran, seit 14:32") und wird beim ersten Zugriff sofort gesetzt.

Erst damit lässt sich vor einem Edit sagen, ob gerade jemand anders an
derselben Stelle arbeitet.

Ablage: eine Datei pro Person unter reservierungen/, genau wie beim
Status. Jede Session schreibt nur in ihre eigene Datei, deshalb kann es
keine Konflikte geben.

    ---
    typ: reservierungen
    person: lars
    branch: feature/auth
    session: abc123
    aktualisiert: 2026-08-17 14:32
    ---

    - `src/auth.py` seit 2026-08-17 14:32
    - `src/user.py` seit 2026-08-17 14:40
"""

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import frontmatter
from .channel import (
    ChannelLock,
    channel_is_ready,
    now_stamp,
    parse_stamp,
    push_channel,
    read_text,
    slugify,
    write_text_lf,
)

# Wie lange eine Reservierung gilt. Eine, die zu lange hält, ist
# schlimmer als gar keine: Sie erzeugt Fehlalarme für Sessions, die
# längst beendet sind, und nach dem dritten Fehlalarm wird die Warnung
# überlesen.
GUELTIG_STUNDEN = int(os.environ.get("TEAM_SYNC_RESERVIERUNG_STUNDEN", "4"))

ORDNER = "reservierungen"

_ZEILE = re.compile(r"^-\s+`([^`]+)`\s+seit\s+(.+?)\s*$")


def normalisiere(datei, project_dir=None) -> str:
    """
    Bringt einen Dateipfad auf eine Form, die auf jedem Rechner gleich
    aussieht: projektrelativ und mit Schrägstrichen.

    Das ist keine Kosmetik. Bleibt ein absoluter Pfad stehen, reserviert
    Person A "C:/Users/lars/projekt/auth.py" und Person B sucht nach
    "/home/max/projekt/auth.py" — dieselbe Datei, zwei Einträge, und die
    Kollision fällt nie auf.

    Deshalb zwei Wege zum Ziel: erst der saubere über relative_to, dann
    ein Vergleich der Pfadanfänge ohne Rücksicht auf Groß- und
    Kleinschreibung. Letzterer fängt Windows-Fälle ab, in denen derselbe
    Ort mal als "C:\\Users" und mal als "c:\\users" ankommt.
    """
    if not datei:
        return ""

    text = str(datei)
    if not project_dir:
        return text.replace("\\", "/")

    try:
        aufgeloest = Path(text).resolve()
        wurzel = Path(project_dir).resolve()
    except Exception:
        return text.replace("\\", "/")

    try:
        return str(aufgeloest.relative_to(wurzel)).replace("\\", "/")
    except Exception:
        pass

    # Zweiter Versuch, unempfindlich gegen Schreibweise.
    kandidat = os.path.normcase(str(aufgeloest))
    basis = os.path.normcase(str(wurzel)).rstrip("\\/")
    if kandidat.startswith(basis + os.sep) or kandidat.startswith(basis + "/"):
        return str(aufgeloest)[len(str(wurzel)):].lstrip("\\/").replace("\\", "/")

    return str(aufgeloest).replace("\\", "/")


def _datei_pfad(channel_dir: Path, person: str) -> Path:
    return channel_dir / ORDNER / f"{slugify(person)}.md"


def _bauen(person, branch, session, eintraege) -> str:
    zeilen = []
    for datei, seit in eintraege:
        zeilen.append(f"- `{datei}` seit {seit}")

    return frontmatter.build(
        {
            "typ": "reservierungen",
            "person": person,
            "branch": branch,
            "session": session or "",
            "aktualisiert": now_stamp(),
        },
        "\n".join(zeilen) if zeilen else "_keine_",
    )


def _lesen(pfad: Path):
    """Liest eine Reservierungsdatei zu (kopf, [(datei, seit), ...])."""
    felder, rumpf = frontmatter.parse(read_text(pfad))
    eintraege = []
    for zeile in rumpf.splitlines():
        treffer = _ZEILE.match(zeile.strip())
        if treffer:
            eintraege.append((treffer.group(1).strip(), treffer.group(2).strip()))
    return felder, eintraege


def _ist_abgelaufen(seit: str) -> bool:
    zeitpunkt = parse_stamp(seit)
    if zeitpunkt is None:
        # Unlesbarer Zeitstempel: lieber als abgelaufen behandeln, als
        # eine Datei auf unbestimmte Zeit zu blockieren.
        return True
    return datetime.now() - zeitpunkt > timedelta(hours=GUELTIG_STUNDEN)


def eigene_lesen(channel_dir: Path, person: str):
    return _lesen(_datei_pfad(channel_dir, person))


def alle_fremden(channel_dir: Path, person: str):
    """
    Alle gültigen Reservierungen der anderen.

    Rückgabe: Liste von dicts mit person, branch, session, datei, seit.
    Abgelaufene Einträge fallen hier heraus, unabhängig davon, ob sie
    noch in der Datei stehen.
    """
    ordner = channel_dir / ORDNER
    ergebnis = []

    try:
        if not ordner.is_dir():
            return ergebnis
        dateien = sorted(ordner.glob("*.md"))
    except Exception:
        return ergebnis

    eigener_slug = slugify(person)
    for pfad in dateien:
        if slugify(pfad.stem) == eigener_slug:
            continue
        felder, eintraege = _lesen(pfad)
        for datei, seit in eintraege:
            if _ist_abgelaufen(seit):
                continue
            ergebnis.append(
                {
                    "person": frontmatter.get(felder, "person") or pfad.stem,
                    "branch": frontmatter.get(felder, "branch"),
                    "session": frontmatter.get(felder, "session"),
                    "datei": datei,
                    "seit": seit,
                }
            )
    return ergebnis


def belegt_von(channel_dir: Path, person: str, datei: str):
    """Wer hat genau diese Datei reserviert (außer mir selbst)?"""
    gesucht = datei.lower()
    return [e for e in alle_fremden(channel_dir, person) if e["datei"].lower() == gesucht]


def habe_ich_schon(channel_dir: Path, person: str, datei: str) -> bool:
    _, eintraege = eigene_lesen(channel_dir, person)
    gesucht = datei.lower()
    return any(d.lower() == gesucht for d, _ in eintraege)


def reservieren(channel_dir: Path, person: str, branch: str, session: str,
                datei: str) -> bool:
    """
    Trägt eine Datei in die eigene Reservierungsliste ein und pusht.

    Gibt True zurück, wenn wirklich reserviert wurde, False wenn die
    Datei schon drinstand. Der zweite Fall ist der häufige — bei jedem
    weiteren Edit derselben Datei — und muss billig bleiben, sonst
    entsteht pro Edit ein Push.
    """
    if not channel_is_ready(channel_dir) or not datei:
        return False

    with ChannelLock(channel_dir):
        pfad = _datei_pfad(channel_dir, person)
        _, eintraege = _lesen(pfad)

        gesucht = datei.lower()
        # Abgelaufene Einträge beim Schreiben gleich mit aufräumen.
        behalten = [
            (d, s) for d, s in eintraege
            if d.lower() != gesucht and not _ist_abgelaufen(s)
        ]
        if len(behalten) == len(eintraege) and any(
            d.lower() == gesucht for d, _ in eintraege
        ):
            return False

        behalten.append((datei, now_stamp()))
        behalten.sort()

        try:
            pfad.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(pfad, _bauen(person, branch, session, behalten))
        except Exception:
            return False

        push_channel(channel_dir, f"reserviert: {person} - {datei}")

    return True


def freigeben(channel_dir: Path, person: str, branch: str, session: str,
              datei=None) -> bool:
    """
    Gibt eine einzelne Datei frei, oder alle, wenn datei None ist.

    Die Freigabe beim Sessionende ist kein Beiwerk: Ohne sie hält eine
    beendete Session ihre Dateien bis zum Ablauf besetzt, und die
    anderen bekommen stundenlang Warnungen vor jemandem, der längst
    Feierabend hat.
    """
    if not channel_is_ready(channel_dir):
        return False

    with ChannelLock(channel_dir):
        pfad = _datei_pfad(channel_dir, person)
        if not pfad.is_file():
            return False

        _, eintraege = _lesen(pfad)
        if not eintraege:
            return False

        if datei is None:
            behalten = []
            nachricht = f"freigegeben: {person} - alle"
        else:
            gesucht = normalisiere(datei).lower()
            behalten = [(d, s) for d, s in eintraege if d.lower() != gesucht]
            if len(behalten) == len(eintraege):
                return False
            nachricht = f"freigegeben: {person} - {datei}"

        try:
            write_text_lf(pfad, _bauen(person, branch, session, behalten))
        except Exception:
            return False

        push_channel(channel_dir, nachricht)

    return True


def beschreibe(eintrag) -> str:
    """Kurze, lesbare Fassung einer Reservierung."""
    from .channel import describe_age

    alter = describe_age(eintrag["seit"])
    teile = [eintrag["person"]]
    if alter:
        teile.append(f"seit {alter.replace('vor ', '')}")
    if eintrag.get("branch"):
        teile.append(f"Branch {eintrag['branch']}")
    return ", ".join(teile)
