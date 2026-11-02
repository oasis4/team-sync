"""
Wer gehört zum Team, und wen meint ein Name.

Jede Person steht im Channel unter dem Slug ihres git-Namens, also
"max-mustermann". Geschrieben wird im Alltag aber "/ask max" oder
"@max". Bis 0.4 landete eine solche Frage unter "an: max" und kam bei
Max nie an, weil sein Name im Channel ein anderer war. Es gab keine
Fehlermeldung, nur Stille, und Stille ist hier der teuerste Fehler.

Deshalb wird ein Name beim Schreiben gegen die Personen aufgelöst, die
der Channel schon kennt. Ist er eindeutig, wird der volle Name
eingetragen. Ist er mehrdeutig, bricht der Aufruf mit den Kandidaten
ab, statt zu raten. Ist er unbekannt, wird trotzdem geschrieben, aber
mit einer deutlichen Warnung, denn die Person kann schlicht noch nie
eine Session geöffnet haben.
"""

from pathlib import Path

from . import frontmatter
from .channel import list_files_sorted, read_text, slugify

ALLE = frontmatter.ALLE


def bekannte(channel_dir: Path):
    """
    Alle Personen, die im Channel schon etwas hinterlassen haben.

    Quellen sind die Dateinamen in status/ und reservierungen/ und die
    Absender von Fragen, Entscheidungen und Nachrichten. Bewusst nicht
    die Empfänger: Dort kann ein falsch geschriebener Name stehen, und
    der soll sich nicht selbst bestätigen.
    """
    gefunden = set()

    for ordner in ("status", "reservierungen"):
        for pfad in list_files_sorted(channel_dir / ordner):
            gefunden.add(slugify(pfad.stem))

    for ordner, feld in (("questions", "von"), ("decisions", "person"),
                         ("nachrichten", "von")):
        for pfad in list_files_sorted(channel_dir / ordner):
            felder, _ = frontmatter.parse(read_text(pfad))
            wert = frontmatter.get(felder, feld)
            if wert:
                gefunden.add(slugify(wert))

    gefunden.discard("unbekannt")
    gefunden.discard("")
    return sorted(gefunden)


class Aufloesung:
    """Ergebnis einer Namensauflösung."""

    def __init__(self, eingabe, slug, bekannt, kandidaten=None):
        self.eingabe = eingabe
        self.slug = slug
        self.bekannt = bekannt
        self.kandidaten = kandidaten or []

    @property
    def mehrdeutig(self) -> bool:
        return len(self.kandidaten) > 1

    @property
    def ist_alle(self) -> bool:
        return self.slug == ALLE


def aufloesen(channel_dir: Path, name: str) -> Aufloesung:
    """
    Macht aus einem eingegebenen Namen den Slug, unter dem die Person
    im Channel steht.

    Reihenfolge: das ganze Team, ein exakter Treffer, dann ein Treffer
    auf einen Namensteil, also Vor- oder Nachname.
    """
    slug = slugify(name.lstrip("@"))
    if slug in frontmatter.ALLE_SYNONYME:
        return Aufloesung(name, ALLE, True)

    team = bekannte(channel_dir)
    if slug in team:
        return Aufloesung(name, slug, True)

    treffer = [person for person in team if slug in person.split("-")]
    if len(treffer) == 1:
        return Aufloesung(name, treffer[0], True)
    if len(treffer) > 1:
        return Aufloesung(name, slug, False, treffer)

    return Aufloesung(name, slug, False)


def warnung_unbekannt(aufloesung: Aufloesung, team) -> str:
    """Der Hinweis, wenn ein Name im Channel noch nicht vorkommt."""
    bekannt = ", ".join(team) if team else "noch niemand"
    return (
        f"Achtung: Im Channel ist bisher niemand namens '{aufloesung.eingabe}' "
        f"bekannt. Bekannt sind: {bekannt}.\n"
        f"Abgelegt wird es trotzdem unter '{aufloesung.slug}'. Es kommt an, "
        f"sobald jemand mit diesem Vor- oder Nachnamen eine Session öffnet. "
        f"Ist es ein Tippfehler, lieber neu schreiben."
    )
