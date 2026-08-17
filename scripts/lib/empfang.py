"""
Der Rückkanal: was seit dem letzten Blick im Channel passiert ist.

Ohne diesen Teil bleibt alles andere halb wirksam. Wer morgens eine
Session öffnet und bis mittags durcharbeitet, bekommt eine Antwort auf
seine Anfrage erst am nächsten Tag — und in der Zwischenzeit steht die
Arbeit oder wird doppelt gemacht.

Gemeldet wird nur, was den Empfänger wirklich betrifft und was er noch
nicht gesehen hat. Eine Meldung, die bei jedem Durchlauf dasselbe sagt,
wird nach dem zweiten Mal ignoriert und macht den Kanal wertlos.

Was zuletzt gemeldet wurde, steht im Git-Verzeichnis und wird nie
synchronisiert. Es ist eine Notiz darüber, was diese eine Session schon
weiß.
"""

import json
import os
from pathlib import Path

from . import anfrage, frontmatter, render, reservierung
from .channel import (
    describe_age,
    get_git_dir,
    list_files_sorted,
    read_text,
    slugify,
)

# Wie oft überhaupt nachgesehen wird. Deutlich häufiger als der
# Zwischenstand geschrieben wird: Lesen ist billig, und die Latenz
# beim Empfangen ist genau das, was hier verkürzt werden soll.
INTERVALL_SEKUNDEN = int(os.environ.get("TEAM_SYNC_EMPFANG_SECONDS", "120"))


def _merker_pfad(project_dir: Path):
    git_dir = get_git_dir(project_dir)
    return (git_dir / "team-sync-empfang.json") if git_dir else None


def _gesehen_laden(project_dir: Path):
    pfad = _merker_pfad(project_dir)
    if pfad is None or not pfad.exists():
        return set()
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        return set(daten.get("gesehen", []))
    except Exception:
        return set()


def _gesehen_speichern(project_dir: Path, gesehen):
    pfad = _merker_pfad(project_dir)
    if pfad is None:
        return
    try:
        # Nur die jüngsten behalten, sonst wächst die Datei über Monate.
        pfad.write_text(
            json.dumps({"gesehen": sorted(gesehen)[-500:]}), encoding="utf-8"
        )
    except Exception:
        pass


def faellig(project_dir: Path) -> bool:
    import time

    pfad = _merker_pfad(project_dir)
    if pfad is None or not pfad.exists():
        return True
    try:
        return (time.time() - pfad.stat().st_mtime) >= INTERVALL_SEKUNDEN
    except Exception:
        return True


def neuigkeiten(channel_dir: Path, project_dir: Path, me: str):
    """
    Sammelt, was für mich neu ist, und merkt es sich als gesehen.

    Rückgabe: Text für die laufende Session, oder "" wenn nichts anliegt.
    """
    gesehen = _gesehen_laden(project_dir)
    frisch = set()
    bloecke = []

    # 1. Antworten auf meine Dateianfragen. Das ist das Dringlichste:
    #    Hier wartet jemand darauf, weiterarbeiten zu können.
    beantwortet = []
    for eintrag in anfrage.alle(channel_dir):
        if eintrag["status"] == "offen":
            continue
        if not frontmatter.matches_person(eintrag["von"], me):
            continue
        kennung = f"antwort:{eintrag['id']}"
        if kennung in gesehen:
            continue
        frisch.add(kennung)
        beantwortet.append(eintrag)

    if beantwortet:
        zeilen = ["## Antwort auf deine Anfrage", ""]
        for eintrag in beantwortet:
            zeilen.append(
                f"**`{eintrag['datei']}`** — Antwort von {eintrag['an'] or 'unbekannt'}:"
            )
            zeilen.append("")
            zeilen.append(anfrage.nur_antwort(eintrag["body"])[:600])
            zeilen.append("")
        zeilen.append(
            "Wenn du diese Datei zurückgestellt hattest, kannst du jetzt "
            "darauf zurückkommen."
        )
        bloecke.append("\n".join(zeilen))

    # 2. Neue Fragen an mich, einschließlich Dateianfragen. Bei einer
    #    Dateianfrage wartet die andere Session auf mich.
    offene = render.open_questions_for(channel_dir, me)
    neue_fragen = []
    for eintrag in offene:
        kennung = f"frage:{eintrag['path'].stem}"
        if kennung in gesehen:
            continue
        frisch.add(kennung)
        neue_fragen.append(eintrag)

    if neue_fragen:
        zeilen = ["## Neue Frage an dich", ""]
        for eintrag in neue_fragen:
            felder, _ = frontmatter.parse(read_text(eintrag["path"]))
            datei = frontmatter.get(felder, "datei")
            if datei:
                zeilen.append(
                    f"**{eintrag['von']} will an `{datei}`**, die du reserviert "
                    f"hast. Antworte kurz — die andere Session hat die Datei "
                    f"zurückgestellt und wartet."
                )
            else:
                zeilen.append(f"**Von {eintrag['von']}:** {eintrag['titel'] or ''}")
            zeilen.append("")
            zeilen.append(render._ohne_ueberschrift(eintrag["body"])[:400])
            zeilen.append("")
            zeilen.append(
                f'Antworten mit: `team_sync.py answer --id {eintrag["path"].stem} '
                f'--text "..."`'
            )
            zeilen.append("")
        bloecke.append("\n".join(zeilen))

    # 3. Neue Entscheidungen. Sie gelten fürs ganze Team, auch mitten in
    #    einer laufenden Session.
    neue_entscheidungen = []
    for pfad in list_files_sorted(channel_dir / "decisions"):
        kennung = f"entscheidung:{pfad.stem}"
        if kennung in gesehen:
            continue
        frisch.add(kennung)
        eintrag = render.read_decision(pfad)
        if slugify(eintrag["person"] or "") != slugify(me):
            neue_entscheidungen.append(eintrag)

    if neue_entscheidungen:
        zeilen = ["## Neue Festlegung im Team", ""]
        for eintrag in neue_entscheidungen[-3:]:
            zeilen.append(f"**{eintrag['titel']}** ({eintrag['person']})")
            zeilen.append("")
            zeilen.append(eintrag["body"][:400])
            zeilen.append("")
        zeilen.append("Halte dich ab jetzt daran, auch mitten in dieser Aufgabe.")
        bloecke.append("\n".join(zeilen))

    # 4. Freigewordene Dateien, die ich angefragt hatte.
    freigeworden = []
    for eintrag in anfrage.alle(channel_dir):
        if not frontmatter.matches_person(eintrag["von"], me):
            continue
        datei = eintrag["datei"]
        if not datei:
            continue
        kennung = f"frei:{datei}"
        if kennung in gesehen:
            continue
        if reservierung.belegt_von(channel_dir, me, datei):
            continue
        frisch.add(kennung)
        freigeworden.append(datei)

    if freigeworden:
        liste = ", ".join(f"`{d}`" for d in sorted(set(freigeworden)))
        bloecke.append(
            f"## Wieder frei\n\n{liste} ist nicht mehr reserviert. "
            f"Falls du das zurückgestellt hattest, kannst du jetzt weitermachen."
        )

    if not bloecke:
        _gesehen_speichern(project_dir, gesehen)
        return ""

    _gesehen_speichern(project_dir, gesehen | frisch)

    kopf = (
        "# Neues aus dem Team-Channel\n\n"
        "Das ist seit deinem letzten Blick dazugekommen. Es kommt aus einer "
        "anderen, parallel laufenden Session am selben Repository."
    )
    return kopf + "\n\n" + "\n\n".join(bloecke)


def erstlauf_stumm_schalten(channel_dir: Path, project_dir: Path, me: str):
    """
    Merkt sich alles Vorhandene als gesehen, ohne etwas zu melden.

    Wird beim Sessionstart aufgerufen. Ohne das würde der erste
    Rückkanal-Durchlauf alles wiederholen, was der Sessionstart-Kontext
    gerade schon geliefert hat.
    """
    gesehen = _gesehen_laden(project_dir)

    for eintrag in anfrage.alle(channel_dir):
        gesehen.add(f"antwort:{eintrag['id']}")
    for eintrag in render.open_questions_for(channel_dir, me):
        gesehen.add(f"frage:{eintrag['path'].stem}")
    for pfad in list_files_sorted(channel_dir / "decisions"):
        gesehen.add(f"entscheidung:{pfad.stem}")

    _gesehen_speichern(project_dir, gesehen)
