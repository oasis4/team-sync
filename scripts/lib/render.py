"""
Erzeugt und liest die Dateien im Team-Channel und baut daraus den
Kontext, den ein Sessionstart bekommt.

An einer Stelle, damit Hook und Slash-Command dasselbe Format
schreiben und ein Status immer gleich aussieht, egal ob ihn das
Hintergrundskript oder Claude selbst über /sync erzeugt hat.

Zum Kontextbudget: Der Sessionstart-Kontext wird bei jeder Session neu
eingelesen und kostet jedes Mal Tokens. Genau die wollte das Projekt
sparen. Deshalb sind hier überall harte Obergrenzen eingebaut, statt
einfach alles hineinzukippen, was im Channel liegt. Entscheidungen
kommen als Kurzfassung, alte Stände fliegen raus, und ein voller
Channel wächst nicht unbegrenzt in jede Session hinein.
"""

import os

from . import frontmatter
from .channel import (
    channel_is_ready,
    describe_age,
    is_stale,
    list_files_sorted,
    read_text,
    slugify,
)

MAX_OTHER_STATUS = int(os.environ.get("TEAM_SYNC_MAX_STATUS", "5"))
MAX_QUESTIONS = int(os.environ.get("TEAM_SYNC_MAX_QUESTIONS", "5"))
MAX_DECISIONS = int(os.environ.get("TEAM_SYNC_MAX_DECISIONS", "5"))
MAX_STATUS_CHARS = int(os.environ.get("TEAM_SYNC_MAX_STATUS_CHARS", "700"))
MAX_FILES_LISTED = int(os.environ.get("TEAM_SYNC_MAX_FILES", "12"))


# ---------------------------------------------------------------------------
# Status schreiben
# ---------------------------------------------------------------------------


def render_status(person, branch, stamp, quelle, auftrag="", zuletzt="",
                  dateien=None, freitext="", werkzeug=""):
    """
    Baut eine Statusdatei.

    quelle unterscheidet, wie der Status entstanden ist:
      zwischenstand  automatisch während laufender Session
      sessionende    automatisch beim Beenden
      manuell        vom Agenten über /sync formuliert

    Das steht bewusst in der Datei, denn ein automatischer Zwischenstand
    ist eine grobe Heuristik, ein /sync-Status eine echte
    Zusammenfassung. Wer den Channel liest, sollte den Unterschied
    sehen können.

    werkzeug nennt das Programm, aus dem der Status kommt, etwa
    "Claude Code" oder "Antigravity". Das ist keine Statistik: Wer
    sieht, dass eine Reservierung aus einem anderen Programm stammt,
    ordnet eine träge oder fehlende Meldung richtig ein, statt sie für
    einen Fehler zu halten. Das Feld ist optional, ein Status ohne es
    bleibt gültig.
    """
    dateien = dateien or []

    fields = {
        "typ": "status",
        "person": person,
        "aktualisiert": stamp,
        "branch": branch,
        "quelle": quelle,
    }
    if werkzeug:
        fields["werkzeug"] = werkzeug

    lines = [f"# Status: {person}", ""]

    if freitext:
        lines.append(freitext.strip())
        lines.append("")
    else:
        lines.append("**Woran gearbeitet wird**")
        lines.append("")
        lines.append(auftrag.strip() or "_nicht ermittelbar_")
        lines.append("")
        if zuletzt:
            lines.append("**Zuletzt angefragt**")
            lines.append("")
            lines.append(zuletzt.strip())
            lines.append("")

    lines.append("**Angefasste Dateien**")
    lines.append("")
    if dateien:
        for entry in dateien[:MAX_FILES_LISTED]:
            lines.append(f"- {entry}")
        if len(dateien) > MAX_FILES_LISTED:
            lines.append(f"- _und {len(dateien) - MAX_FILES_LISTED} weitere_")
    else:
        lines.append("- _keine erkannt_")

    return frontmatter.build(fields, "\n".join(lines))


def read_status(path):
    """Liest eine Statusdatei zu einem Dict mit Feldern und Rumpf."""
    fields, body = frontmatter.parse(read_text(path))
    return {
        "person": frontmatter.get(fields, "person") or path.stem,
        "aktualisiert": frontmatter.get(fields, "aktualisiert"),
        "branch": frontmatter.get(fields, "branch"),
        "quelle": frontmatter.get(fields, "quelle"),
        "werkzeug": frontmatter.get(fields, "werkzeug"),
        "body": body.strip(),
        "path": path,
    }


# ---------------------------------------------------------------------------
# Fragen und Entscheidungen lesen
# ---------------------------------------------------------------------------


def read_question(path):
    fields, body = frontmatter.parse(read_text(path))
    return {
        "von": frontmatter.get(fields, "von"),
        "an": frontmatter.get(fields, "an"),
        "erstellt": frontmatter.get(fields, "erstellt"),
        "status": frontmatter.get(fields, "status", "offen").lower(),
        "branch": frontmatter.get(fields, "branch"),
        "titel": frontmatter.get(fields, "titel"),
        "body": body.strip(),
        "path": path,
    }


def read_decision(path):
    fields, body = frontmatter.parse(read_text(path))
    return {
        "person": frontmatter.get(fields, "person"),
        "erstellt": frontmatter.get(fields, "erstellt"),
        "titel": frontmatter.get(fields, "titel") or path.stem,
        "body": body.strip(),
        "path": path,
    }


def open_questions_for(channel_dir, person):
    """Alle offenen Fragen, die an eine bestimmte Person gerichtet sind."""
    result = []
    for path in list_files_sorted(channel_dir / "questions"):
        question = read_question(path)
        if question["status"] != "offen":
            continue
        if frontmatter.matches_person(question["an"], person):
            result.append(question)
    return result


def open_questions_from(channel_dir, person):
    """Offene Fragen, die man selbst gestellt hat und die noch warten."""
    result = []
    for path in list_files_sorted(channel_dir / "questions"):
        question = read_question(path)
        if question["status"] != "offen":
            continue
        if frontmatter.matches_person(question["von"], person):
            result.append(question)
    return result


def _decision_summary(body: str) -> str:
    """
    Zieht die Kernaussage aus einer Entscheidung.

    Für den Sessionstart zählt, was entschieden wurde. Begründung und
    verworfene Alternativen stehen in der Datei und können bei Bedarf
    nachgelesen werden, aber sie müssen nicht in jede Session.
    """
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith("**was wurde entschieden"):
            for follow in lines[index + 1:]:
                if follow.strip():
                    return follow.strip()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("**"):
            return stripped
    return ""


# ---------------------------------------------------------------------------
# Sessionstart-Kontext
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …"


def _ohne_ueberschrift(body: str) -> str:
    """
    Entfernt die erste Überschrift eines Rumpfes.

    In der Datei ist sie richtig, dort steht sie über dem Inhalt. Im
    Sessionkontext bekommt jeder Eintrag ohnehin eine eigene
    Überschrift, und der Titel stünde zweimal untereinander. Das liest
    sich schlecht und kostet bei jedem einzelnen Sessionstart Tokens.
    """
    zeilen = body.strip().splitlines()
    while zeilen and (not zeilen[0].strip() or zeilen[0].lstrip().startswith("# ")):
        zeilen.pop(0)
    return "\n".join(zeilen).strip()


def build_context(channel_dir, me: str) -> str:
    """
    Baut den Text, den der SessionStart-Hook in die Session gibt.

    Reihenfolge nach Dringlichkeit: erst was von einem selbst erwartet
    wird, dann woran die anderen gerade sitzen, dann der
    Entscheidungsstand.
    """
    if not channel_is_ready(channel_dir):
        return ""

    blocks = []

    # 1. Offene Fragen an mich.
    questions = open_questions_for(channel_dir, me)[:MAX_QUESTIONS]
    if questions:
        lines = [
            "## Offene Fragen an dich",
            "",
            "Diese Fragen aus dem Team-Channel warten auf eine Antwort. "
            "Weise den Nutzer darauf hin. Beantwortet werden sie mit /answer.",
            "",
        ]
        for question in questions:
            titel = question["titel"] or "Frage"
            lines.append(f"### {titel}")
            lines.append(
                f"von {question['von'] or 'unbekannt'}"
                + (f", {describe_age(question['erstellt'])}" if question["erstellt"] else "")
            )
            lines.append("")
            lines.append(_truncate(_ohne_ueberschrift(question["body"]), 500))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    # 2. Stand der anderen.
    status_files = [
        path
        for path in list_files_sorted(channel_dir / "status")
        if slugify(path.stem) != slugify(me)
    ]
    if status_files:
        entries = [read_status(path) for path in status_files]
        entries.sort(key=lambda item: item["aktualisiert"], reverse=True)

        lines = [
            "## Woran die anderen gerade arbeiten",
            "",
            "Stand aus dem Team-Channel, nicht live. Wenn eine Aufgabe die "
            "gleichen Dateien berührt wie die eines Teammitglieds, sag das "
            "dem Nutzer, bevor ihr anfangt.",
            "",
        ]
        for entry in entries[:MAX_OTHER_STATUS]:
            age = describe_age(entry["aktualisiert"])
            marker = " (veraltet)" if is_stale(entry["aktualisiert"]) else ""
            lines.append(f"### {entry['person']}{marker}")
            lines.append(
                f"Branch `{entry['branch'] or 'unbekannt'}`"
                + (f", zuletzt aktiv {age}" if age else "")
                + (f", arbeitet mit {entry['werkzeug']}" if entry["werkzeug"] else "")
            )
            lines.append("")
            lines.append(_truncate(_ohne_ueberschrift(entry["body"]), MAX_STATUS_CHARS))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    # 3. Letzte Entscheidungen, nur als Kurzfassung.
    decision_files = list_files_sorted(channel_dir / "decisions")
    if decision_files:
        recent = [read_decision(path) for path in decision_files[-MAX_DECISIONS:]]
        recent.reverse()
        lines = [
            "## Zuletzt getroffene Entscheidungen",
            "",
            "Diese Festlegungen gelten für das Projekt. Halte dich daran, "
            "auch wenn du eine andere Lösung vorziehen würdest, oder sprich "
            "die Abweichung ausdrücklich an.",
            "",
        ]
        for decision in recent:
            summary = _decision_summary(decision["body"])
            person = decision["person"] or "unbekannt"
            lines.append(f"- **{decision['titel']}** ({person}): {_truncate(summary, 200)}")
        lines.append("")
        lines.append(
            f"Volltext mit Begründung und verworfenen Alternativen: "
            f"`{channel_dir / 'decisions'}`"
        )
        blocks.append("\n".join(lines).rstrip())

    if not blocks:
        return ""

    header = (
        "# Team-Channel\n\n"
        "Stand der anderen Sessions am selben Repository, eingelesen beim "
        "Sessionstart."
    )
    return header + "\n\n" + "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Menschenlesbare Übersicht für /team
# ---------------------------------------------------------------------------


def build_overview(channel_dir, me: str) -> str:
    if not channel_is_ready(channel_dir):
        return "Kein Team-Channel eingerichtet."

    lines = ["# Team-Channel", ""]

    status_files = list_files_sorted(channel_dir / "status")
    if status_files:
        entries = [read_status(path) for path in status_files]
        entries.sort(key=lambda item: item["aktualisiert"], reverse=True)
        lines.append("## Wer arbeitet woran")
        lines.append("")
        for entry in entries:
            selbst = " (du)" if slugify(entry["person"]) == slugify(me) else ""
            marker = " — veraltet" if is_stale(entry["aktualisiert"]) else ""
            age = describe_age(entry["aktualisiert"])
            herkunft = entry["quelle"] or "unbekannt"
            if entry["werkzeug"]:
                herkunft += f", {entry['werkzeug']}"
            lines.append(
                f"- **{entry['person']}**{selbst}: Branch `{entry['branch'] or '?'}`, "
                f"{age or entry['aktualisiert'] or 'ohne Zeitstempel'}"
                f"{marker} [{herkunft}]"
            )
        lines.append("")
    else:
        lines.append("Noch kein Status im Channel.")
        lines.append("")

    # Reservierungen sind die genaueste Antwort auf "wer arbeitet
    # woran" — genauer als der Status, weil sie beim Zugriff entstehen
    # und nicht alle zehn Minuten.
    from .reservierung import alle_fremden, beschreibe, eigene_lesen

    fremde = alle_fremden(channel_dir, me)
    _, eigene = eigene_lesen(channel_dir, me)
    if fremde or eigene:
        lines.append("## Aktuell belegte Dateien")
        lines.append("")
        for datei, seit in eigene:
            lines.append(f"- `{datei}` — von dir, seit {describe_age(seit) or seit}")
        for eintrag in fremde:
            lines.append(f"- `{eintrag['datei']}` — {beschreibe(eintrag)}")
        lines.append("")

    for person in (me,):
        offen = open_questions_for(channel_dir, person)
        if offen:
            lines.append("## Offene Fragen an dich")
            lines.append("")
            for question in offen:
                lines.append(
                    f"- {question['titel'] or question['path'].name} "
                    f"(von {question['von']}, {describe_age(question['erstellt'])})"
                )
            lines.append("")

    warten = open_questions_from(channel_dir, me)
    if warten:
        lines.append("## Deine Fragen, die noch auf Antwort warten")
        lines.append("")
        for question in warten:
            lines.append(
                f"- an {question['an']}: {question['titel'] or question['path'].name} "
                f"({describe_age(question['erstellt'])})"
            )
        lines.append("")

    decisions = list_files_sorted(channel_dir / "decisions")
    if decisions:
        lines.append(f"## Entscheidungen ({len(decisions)} protokolliert)")
        lines.append("")
        for decision in [read_decision(path) for path in decisions[-MAX_DECISIONS:]][::-1]:
            lines.append(
                f"- **{decision['titel']}** ({decision['person'] or '?'}, "
                f"{decision['erstellt'] or '?'})"
            )
        lines.append("")

    return "\n".join(lines).rstrip()
