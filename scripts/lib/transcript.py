"""
Auswertung des Session-Transkripts für die automatischen Statusmeldungen.

Claude Code legt pro Session eine JSONL-Datei an, eine Zeile pro
Ereignis. Daraus ziehen wir zwei Dinge: woran gearbeitet wird und
welche Dateien angefasst wurden.

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

    result["auftrag"] = first[:MAX_TOPIC_CHARS]
    result["zuletzt"] = last[:MAX_TOPIC_CHARS] if last != first else ""
    result["dateien"] = sorted(files)
    return result
