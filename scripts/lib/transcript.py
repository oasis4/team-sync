"""
Auswertung des Session-Transkripts für die automatischen Statusmeldungen.

Claude Code legt pro Session eine JSONL-Datei an, eine Zeile pro
Ereignis. Daraus ziehen wir zwei Dinge: woran gearbeitet wird und
welche Dateien angefasst wurden.

Antigravity legt ebenfalls ein Transkript an, aber in einem anderen
Format, und dieses Format ist nicht festgeschrieben. Deshalb gibt es
hier zwei Wege: den genauen für Claude Code und einen nachgiebigen,
der ein unbekanntes Transkript nach Nutzertext durchsucht, ohne eine
bestimmte Struktur vorauszusetzen. Liefert auch der nichts, bleibt der
Status eben dünner. Die Liste der angefassten Dateien hängt nicht am
Transkript, sie kommt aus den eigenen Hooks (siehe channel.datei_merken),
und ist deshalb unter beiden Programmen gleich verlässlich.

Bewusst ohne zusätzlichen KI-Aufruf. Jeder Teammitglied bezahlt sein
Kontingent selbst, und ein Hintergrundskript, das bei jedem
Zwischenstand ungefragt Kontingent verbraucht, wäre ein schlechter
Tausch für eine Statuszeile. Wer eine echte Zusammenfassung will,
nimmt /sync, dort formuliert Claude sie im laufenden Kontext.

Die Heuristik ist entsprechend einfach, aber nicht naiv: Sie überspringt
alles, was nur technisches Rauschen ist (Tool-Ergebnisse,
System-Reminder, Hook-Ausgaben, Slash-Command-Rümpfe), und merkt sich
sowohl den ursprünglichen Auftrag als auch die zuletzt gestellte
Aufgabe. Nur die letzte Nachricht zu nehmen, wie es der erste Entwurf
tat, liefert im Alltag oft nur ein "ja, mach weiter" als Status.
"""

import json
from pathlib import Path

# Dateibearbeitende Werkzeuge. Nur diese zählen als "angefasst".
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Nachrichten, die keine echte Nutzeräußerung sind.
NOISE_PREFIXES = (
    "<system-reminder",
    "<command-name",
    "<command-message",
    "<command-args",
    "<local-command",
    "caveat: the messages below",
    "[request interrupted",
)

MAX_TOPIC_CHARS = 220
MAX_LINES = 200_000


def _clean_text(text: str) -> str:
    """Entfernt eingebettete System-Reminder aus einer Nachricht."""
    if not text:
        return ""
    while "<system-reminder>" in text:
        start = text.index("<system-reminder>")
        end = text.find("</system-reminder>", start)
        if end == -1:
            text = text[:start]
            break
        text = text[:start] + text[end + len("</system-reminder>"):]
    return " ".join(text.split()).strip()


def _is_noise(text: str) -> bool:
    if not text:
        return True
    lowered = text.lstrip().lower()
    return any(lowered.startswith(prefix) for prefix in NOISE_PREFIXES)


def _extract_user_text(message) -> str:
    """Holt den reinen Text einer Nutzernachricht, ohne Tool-Ergebnisse."""
    content = message.get("content")

    if isinstance(content, str):
        return _clean_text(content)

    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            # tool_result-Blöcke sind Werkzeugausgaben, keine Äußerung
            # des Nutzers, und würden den Status mit Logzeilen fluten.
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return _clean_text(" ".join(parts))

    return ""


def _relativize(file_path: str, project_dir) -> str:
    if not project_dir:
        return file_path
    try:
        return str(Path(file_path).resolve().relative_to(Path(project_dir).resolve()))
    except Exception:
        return file_path


def summarize(transcript_path, project_dir=None):
    """
    Wertet ein Transkript aus.

    Rückgabe: dict mit
      auftrag  erste inhaltliche Nutzernachricht der Session
      zuletzt  letzte inhaltliche Nutzernachricht
      dateien  sortierte Liste angefasster Dateien, projektrelativ
    """
    result = {"auftrag": "", "zuletzt": "", "dateien": []}

    if not transcript_path:
        return result

    path = Path(transcript_path)
    try:
        if not path.is_file():
            return result
    except Exception:
        return result

    first = ""
    last = ""
    files = set()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle):
                if line_number > MAX_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue

                kind = entry.get("type")
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue

                if kind == "user":
                    text = _extract_user_text(message)
                    if _is_noise(text):
                        continue
                    if not first:
                        first = text
                    last = text

                elif kind == "assistant":
                    content = message.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue
                        if block.get("name") not in EDIT_TOOLS:
                            continue
                        tool_input = block.get("input")
                        if not isinstance(tool_input, dict):
                            continue
                        file_path = tool_input.get("file_path") or tool_input.get(
                            "notebook_path"
                        )
                        if file_path:
                            files.add(_relativize(str(file_path), project_dir))
    except Exception:
        # Ein unlesbares Transkript ist kein Grund, den Hook scheitern
        # zu lassen. Dann gibt es diesmal eben einen dünneren Status.
        pass

    if not first:
        # Kein Treffer im Claude-Code-Format. Entweder war die Datei
        # leer, oder sie stammt aus einem anderen Programm. Der zweite
        # Weg setzt keine Struktur voraus.
        first, last = _generischer_text(path)

    result["auftrag"] = first[:MAX_TOPIC_CHARS]
    result["zuletzt"] = last[:MAX_TOPIC_CHARS] if last != first else ""
    result["dateien"] = sorted(files)
    return result


# ---------------------------------------------------------------------------
# Nachgiebiger Weg für fremde Transkriptformate
# ---------------------------------------------------------------------------

# Werte des Typ- oder Rollenfeldes, die eine Nutzeräußerung ankündigen.
# Antigravity kennt unter anderem USER_MESSAGE neben PLANNER_RESPONSE;
# aufgenommen sind hier auch die Schreibweisen anderer Werkzeuge, denn
# ein zusätzlicher Eintrag kostet nichts und ein fehlender kostet den
# halben Status.
NUTZER_TYPEN = {
    "user", "usermessage", "userturn", "userinput", "userrequest",
    "human", "humanmessage", "humanturn", "input", "prompt",
}

# Felder, in denen der Text einer solchen Äußerung stehen kann.
TEXT_FELDER = ("text", "content", "message", "prompt", "usermessage", "query", "value")

MAX_GENERISCHE_TIEFE = 4


def _normalisiere(name) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


def _text_aus(wert, tiefe=0) -> str:
    """Zieht lesbaren Text aus einem beliebig verschachtelten Wert."""
    if tiefe > MAX_GENERISCHE_TIEFE:
        return ""

    if isinstance(wert, str):
        return _clean_text(wert)

    if isinstance(wert, dict):
        for feld in TEXT_FELDER:
            for schluessel, inhalt in wert.items():
                if _normalisiere(schluessel) == feld:
                    text = _text_aus(inhalt, tiefe + 1)
                    if text:
                        return text
        return ""

    if isinstance(wert, list):
        teile = [_text_aus(eintrag, tiefe + 1) for eintrag in wert[:20]]
        return _clean_text(" ".join(teil for teil in teile if teil))

    return ""


def _ist_nutzereintrag(eintrag) -> bool:
    for schluessel in ("type", "role", "kind", "eventType", "author", "sender"):
        wert = eintrag.get(schluessel)
        if isinstance(wert, str) and _normalisiere(wert) in NUTZER_TYPEN:
            return True
    return False


def _eintraege_lesen(path):
    """
    Liest ein Transkript als Liste von Einträgen.

    Deckt beide gängigen Formen ab: eine JSON-Zeile pro Ereignis und ein
    einzelnes JSON-Dokument mit einer Liste darin. Welche davon vorliegt,
    gehört dem Hostprogramm und kann sich ändern, deshalb wird nicht
    gefragt, sondern beides versucht.
    """
    eintraege = []
    try:
        roh = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return eintraege

    zeilen = roh.splitlines()
    for nummer, zeile in enumerate(zeilen):
        if nummer > MAX_LINES:
            break
        zeile = zeile.strip()
        if not zeile.startswith(("{", "[")):
            continue
        try:
            geparst = json.loads(zeile)
        except Exception:
            continue
        if isinstance(geparst, dict):
            eintraege.append(geparst)
        elif isinstance(geparst, list):
            eintraege.extend(e for e in geparst if isinstance(e, dict))

    if eintraege:
        return eintraege

    # Kein zeilenweises Format: das Ganze als ein Dokument versuchen.
    try:
        geparst = json.loads(roh)
    except Exception:
        return eintraege

    if isinstance(geparst, list):
        return [e for e in geparst if isinstance(e, dict)]
    if isinstance(geparst, dict):
        for wert in geparst.values():
            if isinstance(wert, list) and any(isinstance(e, dict) for e in wert):
                return [e for e in wert if isinstance(e, dict)]
    return eintraege


def _generischer_text(path):
    """
    Sucht die erste und die letzte Nutzeräußerung in einem beliebigen
    Transkript.

    Rückgabe: (erste, letzte). Findet sich nichts, zweimal "". Der
    Status ist dann dünner, aber er entsteht trotzdem, und die Liste der
    angefassten Dateien und der Zeitstempel stimmen weiterhin.
    """
    erste = ""
    letzte = ""

    for eintrag in _eintraege_lesen(path):
        if not _ist_nutzereintrag(eintrag):
            continue
        text = _text_aus(eintrag)
        if _is_noise(text):
            continue
        if not erste:
            erste = text
        letzte = text

    return erste, letzte
