"""
Unterstützung für mehr als ein Hostprogramm.

team-sync ist als Claude-Code-Plugin entstanden. Der Kanal selbst ist
aber nur ein Git-Branch mit Markdown-Dateien, und dem ist gleich,
welches Programm ihn beschreibt. Damit auch jemand mitarbeiten kann,
der Google Antigravity benutzt, liegt hier die einzige Stelle, an der
sich die beiden Programme wirklich unterscheiden: Form der
Hook-Eingabe, Form der Hook-Ausgabe, Namen der Ereignisse.

Der Rest des Plugins bleibt hostneutral und arbeitet nur noch mit dem
normalisierten Ereignis aus lies_ereignis().

Die beiden Protokolle im Vergleich:

    Claude Code                     Antigravity
    ---------------------------------------------------------------
    tool_name                       toolCall.name
    tool_input.file_path            irgendwo in toolCall
    session_id                      conversationId
    transcript_path                 transcriptPath
    CLAUDE_PROJECT_DIR              workspacePaths[0]

    SessionStart                    PreInvocation (erster Aufruf)
    Stop (nach jeder Antwort)       PostInvocation
    SessionEnd                      Stop
    PreToolUse / PostToolUse        PreToolUse / PostToolUse

    Ausgabe: hookSpecificOutput     Ausgabe: injectSteps bzw. decision

Zur Antigravity-Seite eine ehrliche Vorbemerkung: Das Protokoll ist
weniger festgeschrieben als das von Claude Code und hat sich seit der
ersten Fassung bereits geändert. Alles hier ist deshalb bewusst
nachgiebig gebaut. Unbekannte Felder werden übersprungen, fehlende
Felder ergeben leere Werte, und im Zweifel tut ein Hook lieber nichts
als das Falsche. Ein Hook, der eine fremde Sitzung mit einer Exception
abbricht, wäre der schlechteste Ausgang von allen.
"""

import json
import os
import sys
import time
from pathlib import Path

CLAUDE = "claude"
ANTIGRAVITY = "antigravity"

# Anzeigenamen für den Channel. Wer im Team sieht, dass jemand mit einem
# anderen Programm arbeitet, kann eine träge Reservierung einordnen,
# statt sie für einen Fehler zu halten.
LABELS = {
    CLAUDE: "Claude Code",
    ANTIGRAVITY: "Antigravity",
}

# Werkzeuge, die unter Claude Code eine Datei verändern. Feste Liste,
# weil die Namen dort dokumentiert und stabil sind.
CLAUDE_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Für Antigravity gibt es keine solche Liste. Die Werkzeugnamen hängen
# von Version und Modell ab, deshalb wird über den Namen geraten und
# zusätzlich verlangt, dass überhaupt ein Dateipfad im Aufruf steckt.
# Wer die Namen seiner Installation kennt, setzt sie hart über
# TEAM_SYNC_AG_EDIT_TOOLS und das Raten entfällt.
AG_EDIT_STICHWOERTER = (
    "write", "edit", "create", "replace", "patch", "apply",
    "insert", "modify", "append", "notebook", "save",
)

# Schlüssel, unter denen ein Dateipfad in einem Werkzeugaufruf stehen
# kann. Verglichen wird ohne Unterstriche und ohne Groß- und
# Kleinschreibung, damit file_path, filePath und FilePath dasselbe sind.
PFAD_SCHLUESSEL = {
    "filepath", "path", "file", "targetfile", "absolutepath",
    "notebookpath", "filename", "relativepath", "notebook", "uri",
}

# Schlüssel, unter denen die Argumente eines Werkzeugaufrufs stecken.
ARGUMENT_SCHLUESSEL = ("args", "arguments", "input", "toolinput", "parameters", "params")

# Wie tief in einen Werkzeugaufruf hineingesucht wird. Drei Ebenen
# reichen für jede bisher gesehene Form, und eine Obergrenze schützt
# vor einer Struktur, die sich selbst enthält.
MAX_TIEFE = 4

# Wie lange eine zurückgestellte Meldung gültig bleibt (Sekunden).
# Ein Hinweis auf eine belegte Datei, der eine Viertelstunde alt ist,
# beschreibt meistens nicht mehr die Lage und wird verworfen.
POSTFACH_GUELTIG = int(os.environ.get("TEAM_SYNC_POSTFACH_SECONDS", "900"))


# ---------------------------------------------------------------------------
# Eingabe
# ---------------------------------------------------------------------------


def _normalisiere_schluessel(name: str) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


def _erster_treffer(daten, namen):
    """Holt den ersten vorhandenen Wert aus einem Dict, tolerant benannt."""
    if not isinstance(daten, dict):
        return None
    gesucht = {_normalisiere_schluessel(n) for n in namen}
    for schluessel, wert in daten.items():
        if _normalisiere_schluessel(schluessel) in gesucht:
            return wert
    return None


def _als_dict(wert):
    """
    Macht aus einem Wert ein Dict, auch wenn er als JSON-Text ankommt.

    Manche Hosts reichen die Argumente eines Werkzeugaufrufs als
    Zeichenkette durch. Ohne diesen Schritt bliebe der Dateipfad darin
    unsichtbar.
    """
    if isinstance(wert, dict):
        return wert
    if isinstance(wert, str) and wert.strip().startswith("{"):
        try:
            geparst = json.loads(wert)
            return geparst if isinstance(geparst, dict) else {}
        except Exception:
            return {}
    return {}


def _sieht_nach_pfad_aus(wert) -> bool:
    if not isinstance(wert, str):
        return False
    text = wert.strip()
    if not text or len(text) > 4096:
        return False
    if text.startswith(("http://", "https://", "data:")):
        return False
    if text.startswith("file://"):
        return True
    return "/" in text or "\\" in text or "." in text


def _pfad_suchen(objekt, tiefe=0):
    """
    Sucht rekursiv nach einem Dateipfad in einem Werkzeugaufruf.

    Nötig, weil die Argumentstruktur bei Antigravity nicht festliegt.
    Statt eine Form zu erraten und bei der nächsten Version stumm
    danebenzuliegen, wird nach bekannten Schlüsselnamen gesucht. Findet
    sich keiner, gibt es eben keine Reservierung, und das Plugin
    verhält sich wie vorher.
    """
    if tiefe > MAX_TIEFE:
        return ""

    if isinstance(objekt, dict):
        for schluessel, wert in objekt.items():
            if (
                _normalisiere_schluessel(schluessel) in PFAD_SCHLUESSEL
                and _sieht_nach_pfad_aus(wert)
            ):
                return str(wert).strip()
        for wert in objekt.values():
            if isinstance(wert, (dict, list)):
                treffer = _pfad_suchen(wert, tiefe + 1)
                if treffer:
                    return treffer
            else:
                unterdict = _als_dict(wert)
                if unterdict:
                    treffer = _pfad_suchen(unterdict, tiefe + 1)
                    if treffer:
                        return treffer
        return ""

    if isinstance(objekt, list):
        for eintrag in objekt[:20]:
            treffer = _pfad_suchen(eintrag, tiefe + 1)
            if treffer:
                return treffer

    return ""


def erkenne_host(payload) -> str:
    """
    Rät anhand der Nutzlast, welches Programm den Hook gestartet hat.

    Die Felder sind eindeutig genug, dass keine Umgebungsvariable
    nötig ist. TEAM_SYNC_HOST gibt es trotzdem, für den Fall, dass ein
    künftiges Format hier danebenliegt.
    """
    erzwungen = (os.environ.get("TEAM_SYNC_HOST") or "").strip().lower()
    if erzwungen in (CLAUDE, ANTIGRAVITY):
        return erzwungen

    if isinstance(payload, dict):
        for schluessel in payload:
            normalisiert = _normalisiere_schluessel(schluessel)
            if normalisiert in ("conversationid", "workspacepaths", "stepidx", "toolcall"):
                return ANTIGRAVITY
            if normalisiert in ("sessionid", "toolname", "toolinput", "hookeventname"):
                return CLAUDE

    if os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CLAUDE_SESSION_ID"):
        return CLAUDE
    if os.environ.get("ANTIGRAVITY_WORKSPACE") or os.environ.get("GEMINI_CLI"):
        return ANTIGRAVITY

    return CLAUDE


class Ereignis:
    """
    Ein Hook-Aufruf, unabhängig davon, wer ihn ausgelöst hat.

    Alle Felder sind immer gesetzt, notfalls leer. Die Hooks fragen nie
    nach, ob ein Feld existiert, sie prüfen nur auf Inhalt.
    """

    def __init__(self, host, payload, ereignis=""):
        self.host = host
        self.payload = payload if isinstance(payload, dict) else {}
        self.ereignis = ereignis

        if host == ANTIGRAVITY:
            self._lies_antigravity()
        else:
            self._lies_claude()

    def _lies_claude(self):
        payload = self.payload
        self.session = str(payload.get("session_id") or "")
        self.transcript = str(payload.get("transcript_path") or "")
        self.werkzeug = str(payload.get("tool_name") or "")
        self.modus = str(payload.get("permission_mode") or "")
        self.grund = str(payload.get("session_end_reason") or "")

        werkzeug_eingabe = payload.get("tool_input")
        if isinstance(werkzeug_eingabe, dict):
            self.datei = str(
                werkzeug_eingabe.get("file_path")
                or werkzeug_eingabe.get("notebook_path")
                or ""
            )
        else:
            self.datei = ""

        self.projekt = os.environ.get("CLAUDE_PROJECT_DIR") or str(payload.get("cwd") or "")

    def _lies_antigravity(self):
        payload = self.payload
        self.session = str(_erster_treffer(payload, ("conversationId", "sessionId")) or "")
        self.transcript = str(
            _erster_treffer(payload, ("transcriptPath", "transcript")) or ""
        )
        self.modus = str(_erster_treffer(payload, ("permissionMode", "mode")) or "")
        self.grund = str(_erster_treffer(payload, ("reason", "endReason")) or "")

        aufruf = _als_dict(_erster_treffer(payload, ("toolCall", "tool")))
        self.werkzeug = str(_erster_treffer(aufruf, ("name", "toolName")) or "")

        # Erst in den Argumenten suchen, dann im ganzen Aufruf. Der
        # zweite Schritt fängt Formen ab, bei denen der Pfad direkt
        # neben dem Namen steht statt in einem Argumentblock.
        argumente = _als_dict(_erster_treffer(aufruf, ARGUMENT_SCHLUESSEL))
        self.datei = _pfad_suchen(argumente) or _pfad_suchen(aufruf)
        if self.datei.startswith("file://"):
            self.datei = self.datei[len("file://"):]

        self.projekt = _arbeitsordner(payload)

    def ist_edit(self) -> bool:
        """
        Verändert dieser Werkzeugaufruf eine Datei?

        Unter Claude Code ist das eine Frage der festen Liste. Unter
        Antigravity wird der Name geprüft und zusätzlich verlangt, dass
        ein Pfad dabei ist, denn ein Lesezugriff darf keine
        Reservierung auslösen.
        """
        if self.host == CLAUDE:
            return self.werkzeug in CLAUDE_EDIT_TOOLS

        if not self.datei:
            return False

        eigene = os.environ.get("TEAM_SYNC_AG_EDIT_TOOLS", "").strip()
        if eigene:
            erlaubt = {_normalisiere_schluessel(n) for n in eigene.split(",") if n.strip()}
            return _normalisiere_schluessel(self.werkzeug) in erlaubt

        name = self.werkzeug.lower()
        if not name:
            return False
        return any(stichwort in name for stichwort in AG_EDIT_STICHWOERTER)

    @property
    def label(self) -> str:
        return LABELS.get(self.host, self.host)


def _arbeitsordner(payload) -> str:
    """Der Arbeitsordner aus einer Antigravity-Nutzlast."""
    pfade = _erster_treffer(payload, ("workspacePaths", "workspace", "cwd"))
    if isinstance(pfade, str):
        return pfade
    if isinstance(pfade, list):
        for eintrag in pfade:
            if isinstance(eintrag, str) and eintrag.strip():
                return eintrag.strip()
            if isinstance(eintrag, dict):
                wert = _erster_treffer(eintrag, ("path", "uri", "root"))
                if isinstance(wert, str) and wert.strip():
                    return wert.strip()
    return os.environ.get("ANTIGRAVITY_WORKSPACE", "")


def lies_ereignis(ereignis="") -> Ereignis:
    """
    Liest die Hook-Nutzlast von der Standardeingabe und normalisiert sie.

    Nebenwirkung mit Absicht: Steckt in der Nutzlast ein Arbeitsordner,
    wird er als TEAM_SYNC_PROJECT_DIR gesetzt. Alle anderen Module
    ermitteln das Projekt über channel.get_project_dir(), und die hat
    unter Antigravity sonst nichts als das aktuelle Verzeichnis, das
    beim Start eines Hooks alles Mögliche sein kann.
    """
    try:
        roh = sys.stdin.read()
    except Exception:
        roh = ""

    try:
        payload = json.loads(roh) if roh and roh.strip() else {}
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    host = erkenne_host(payload)
    daten = Ereignis(host, payload, ereignis)

    if daten.projekt and not os.environ.get("TEAM_SYNC_PROJECT_DIR"):
        try:
            pfad = daten.projekt
            if pfad.startswith("file://"):
                pfad = pfad[len("file://"):]
            if Path(pfad).is_dir():
                os.environ["TEAM_SYNC_PROJECT_DIR"] = pfad
        except Exception:
            pass

    return daten


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------


def _ausgeben(daten):
    print(json.dumps(daten, ensure_ascii=False))


def melde_kontext(host: str, ereignis: str, text: str):
    """
    Gibt Text in die laufende Sitzung.

    Claude Code nimmt ihn als additionalContext, benannt nach dem
    Ereignis. Antigravity nimmt einen eingeschobenen Schritt mit einer
    flüchtigen Nachricht. Beides landet im Kontext des Modells, nicht
    auf dem Bildschirm des Nutzers.
    """
    if not text:
        return

    if host == ANTIGRAVITY:
        _ausgeben({"injectSteps": [{"ephemeralMessage": text}]})
        return

    _ausgeben(
        {
            "hookSpecificOutput": {
                "hookEventName": ereignis or "SessionStart",
                "additionalContext": text,
            }
        }
    )


def melde_werkzeug_hinweis(host: str, text: str, project_dir=None):
    """
    Hinweis vor einem Werkzeugaufruf.

    Unter Claude Code ist das eine Erlaubnis mit Begleittext in einem
    Zug. Antigravity erwartet an dieser Stelle laut Protokoll genau
    {"decision": "allow"}; ein zusätzliches Feld kann der strenge
    Parser ablehnen, und eine abgelehnte Hook-Antwort hat schon dazu
    geführt, dass jeder Werkzeugaufruf verweigert wurde. Der Hinweis
    wird deshalb zurückgestellt und beim nächsten Modellaufruf über
    PreInvocation nachgereicht. Das kostet einen Schritt Verzögerung
    und ist das allemal wert.
    """
    if host == ANTIGRAVITY:
        if text and project_dir is not None:
            postfach_legen(project_dir, text)
        erlaube(host)
        return

    _ausgeben(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": text,
            }
        }
    )


def erlaube(host: str):
    """Antwort eines PreToolUse-Hooks, der nichts zu sagen hat."""
    if host == ANTIGRAVITY:
        _ausgeben({"decision": "allow"})


def fertig(host: str):
    """Antwort eines Hooks ohne Rückgabe, etwa PostToolUse oder Stop."""
    if host == ANTIGRAVITY:
        _ausgeben({})


# ---------------------------------------------------------------------------
# Postfach für zurückgestellte Meldungen
# ---------------------------------------------------------------------------


def _postfach_pfad(project_dir):
    from .channel import get_git_dir

    git_dir = get_git_dir(Path(project_dir))
    return (git_dir / "team-sync-postfach.json") if git_dir else None


def postfach_legen(project_dir, text: str):
    """
    Hebt eine Meldung auf, die gerade nicht ausgegeben werden kann.

    Liegt im Git-Verzeichnis des Projekts und wird nie synchronisiert.
    Es ist eine Notiz an die eigene Sitzung, sonst niemanden.
    """
    pfad = _postfach_pfad(project_dir)
    if pfad is None or not text:
        return

    eintraege = _postfach_lesen(pfad)
    # Dieselbe Meldung nicht zweimal aufheben. Ein Agent, der dreimal
    # hintereinander dieselbe belegte Datei anfasst, soll den Hinweis
    # einmal bekommen und nicht dreimal.
    if any(eintrag.get("text") == text for eintrag in eintraege):
        return

    eintraege.append({"zeit": time.time(), "text": text})
    try:
        pfad.write_text(
            json.dumps({"meldungen": eintraege[-10:]}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _postfach_lesen(pfad):
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        meldungen = daten.get("meldungen")
        return [e for e in meldungen if isinstance(e, dict)] if isinstance(meldungen, list) else []
    except Exception:
        return []


def postfach_abholen(project_dir) -> str:
    """
    Holt die zurückgestellten Meldungen und leert das Postfach.

    Abgelaufene Einträge fallen still heraus. Ein Hinweis auf eine
    belegte Datei, der eine Viertelstunde alt ist, beschreibt die Lage
    nicht mehr.
    """
    pfad = _postfach_pfad(project_dir)
    if pfad is None or not pfad.exists():
        return ""

    eintraege = _postfach_lesen(pfad)
    try:
        pfad.unlink()
    except Exception:
        pass

    jetzt = time.time()
    texte = [
        eintrag.get("text", "")
        for eintrag in eintraege
        if eintrag.get("text") and (jetzt - float(eintrag.get("zeit", 0))) < POSTFACH_GUELTIG
    ]
    return "\n\n".join(texte)
