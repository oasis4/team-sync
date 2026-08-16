"""
Minimaler Frontmatter-Parser für die Dateien im Team-Channel.

Jede Frage, Entscheidung und jeder Status trägt oben einen Block mit
maschinenlesbaren Feldern:

    ---
    typ: frage
    von: lars
    an: max
    erstellt: 2026-08-16 18:30
    status: offen
    ---

    Freitext ...

Bewusst kein YAML, sondern nur flache "schlüssel: wert"-Zeilen. Damit
braucht das Plugin keine externe Bibliothek, und die Dateien bleiben
für Menschen im GitHub-Diff genauso lesbar wie für die Skripte.

Der Prototyp hat die Empfängersuche noch per Textsuche im ganzen
Dokument gemacht ("steht 'an: max' irgendwo drin"). Das trifft auch auf
eine Frage zu, in deren Fließtext jemand 'an: max' erwähnt, und es
verfehlt jede Frage, die den Namen anders schreibt. Deshalb hier ein
klar abgegrenztes Kopffeld statt Volltextsuche.
"""

from .channel import slugify

DELIM = "---"


def parse(text: str):
    """
    Zerlegt einen Dateiinhalt in (felder, rumpf).

    Ohne Frontmatter kommt ein leeres Feld-Dict und der unveränderte
    Text zurück. Schlüssel werden kleingeschrieben, Werte getrimmt.
    """
    fields = {}
    if not text:
        return fields, ""

    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIM:
        return fields, text

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIM:
            end = index
            break

    if end is None:
        return fields, text

    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key:
            fields[key] = value.strip()

    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return fields, body


def build(fields, body: str) -> str:
    """Baut eine Datei aus Feldern und Rumpf."""
    lines = [DELIM]
    for key, value in fields.items():
        if value is None:
            continue
        clean = str(value).replace("\n", " ").replace("\r", " ").strip()
        lines.append(f"{key}: {clean}")
    lines.append(DELIM)
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    return "\n".join(lines)


def get(fields, key: str, default="") -> str:
    return fields.get(key.lower(), default)


def matches_person(value: str, person: str) -> bool:
    """
    Prüft, ob ein Feldwert eine bestimmte Person meint.

    Vergleicht auf Slug-Ebene und erlaubt mehrere Empfänger, durch
    Komma getrennt. "an: Max Mustermann, lars" trifft also sowohl auf
    "max-mustermann" als auch auf "lars" zu.
    """
    if not value or not person:
        return False

    target = slugify(person)
    return any(slugify(part) == target for part in value.split(","))
