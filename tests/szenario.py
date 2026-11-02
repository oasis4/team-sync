"""
Ein ganzer Arbeitsablauf zweier Teammitglieder, Schritt für Schritt.

Läuft mit genau den Prozessen, die Claude Code auch startet: die Hooks
mit ihren Nutzlasten, der Lauscher als Hintergrundprozess unter einer
Shell, git gegen ein echtes Remote. Was sonst Claude entscheidet, ist
hier fest vorgegeben. Befehle, die das Plugin Claude nennt, werden so
ausgeführt, wie sie in der Meldung stehen, in einer Shell ohne
CLAUDE_PLUGIN_ROOT, so wie Claudes eigene Shell.

Gemessen wird, ob jede Meldung ankommt, wie lange sie braucht und ob
etwas doppelt kommt.

    python3 tests/szenario.py          Zeitleiste ausgeben
    tests/test_szenario.py             derselbe Ablauf als Test

Der Ablauf:

    Lars (Backend) stellt den Betrag auf Cent um und reserviert dabei
    shared/models.py. Max (Frontend) will an dieselbe Datei, wird einmal
    angehalten und fragt per Anfrage nach. Lars wird vom Lauscher
    geweckt und antwortet, Max bekommt die Antwort ebenso. Lars pusht
    und schreibt Max eine Nachricht. Lars beendet die Session, seine
    Reservierungen werden frei, sein Lauscher endet. Danach kann Max
    die Datei ohne Hinweis bearbeiten.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import SCRIPTS, TeamUmgebung, git  # noqa: E402

LAUSCH_SEKUNDEN = 5


class Sitzung:
    """Eine simulierte Claude-Code-Sitzung mit Hooks und Lauscher."""

    def __init__(self, team, person, protokoll):
        self.team = team
        self.person = person
        self.projekt = team.projekte[person]
        self.protokoll = protokoll
        self.meldungen = []
        self.prozess = None

    # -- Hooks ---------------------------------------------------------

    def hook(self, skript, payload, argv=()):
        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / skript)] + list(argv),
            input=json.dumps(payload), capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(self.projekt),
            env=self.team.umgebung(self.person),
        )
        if ergebnis.returncode != 0:
            raise AssertionError(f"{skript} bei {self.person}: {ergebnis.stderr}")
        return json.loads(ergebnis.stdout)["hookSpecificOutput"] if ergebnis.stdout.strip() else {}

    def start(self):
        return self.hook("session_start.py", {"hook_event_name": "SessionStart",
                                              "source": "startup"})

    def eingabe(self, prompt="weiter"):
        return self.hook("prompt_submit.py", {"hook_event_name": "UserPromptSubmit",
                                              "prompt": prompt})

    def stop(self):
        """Beide Stop-Einträge aus hooks.json, Rückkanal und Zwischenstand."""
        return self.hook("session_checkpoint.py", {"hook_event_name": "Stop"})

    def edit(self, relativ, inhalt):
        """PreToolUse, bei Erlaubnis schreiben, dann PostToolUse."""
        payload = {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "session_id": f"s-{self.person}", "permission_mode": "acceptEdits",
            "tool_input": {"file_path": str(self.projekt / relativ)},
        }
        vorher = self.hook("tool_pre_edit.py", payload)
        if vorher.get("permissionDecision") == "deny":
            return vorher
        (self.projekt / relativ).write_text(inhalt, encoding="utf-8")
        payload["hook_event_name"] = "PostToolUse"
        self.hook("tool_post_edit.py", payload)
        return vorher

    def ende(self):
        """SessionEnd wie bei /exit: abgelöst, dann endet die Sitzung."""
        beginn = time.time()
        subprocess.run(
            [sys.executable, str(SCRIPTS / "session_end.py")],
            input=json.dumps({"hook_event_name": "SessionEnd", "reason": "prompt_input_exit",
                              "session_id": f"s-{self.person}"}),
            capture_output=True, text=True, cwd=str(self.projekt),
            env=self.team.umgebung(self.person),
        )
        dauer = time.time() - beginn
        self.beenden()
        return dauer

    # -- Claudes Shell -------------------------------------------------

    def shell(self, befehl):
        """Führt einen Befehl so aus wie Claudes Bash-Werkzeug."""
        umgebung = self.team.umgebung(self.person)
        umgebung.pop("CLAUDE_PLUGIN_ROOT", None)
        ergebnis = subprocess.run(
            ["bash", "-c", befehl], cwd=str(self.projekt), capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=umgebung,
        )
        if ergebnis.returncode != 0:
            raise AssertionError(f"Befehl schlug fehl: {befehl}\n{ergebnis.stderr}")
        return ergebnis.stdout

    # -- Lauscher ------------------------------------------------------

    def lauscher_starten(self):
        """
        Wie Claude Code: ein Prozess (hier ein Stellvertreter) startet
        eine Shell, die den Lauscher startet. Seine Ausgabe sind die
        Benachrichtigungen an Claude.
        """
        befehl = f'"{sys.executable}" "{SCRIPTS / "lauschen.py"}" "{self.projekt}"'
        stellvertreter = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen(['sh', '-c', {befehl!r}])\n"
            "time.sleep(3600)\n"
        )
        self.prozess = subprocess.Popen(
            [sys.executable, "-c", stellvertreter], cwd=str(self.projekt),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            env=self.team.umgebung(self.person, {
                "TEAM_SYNC_LAUSCHEN_SECONDS": str(LAUSCH_SEKUNDEN),
                "TEAM_SYNC_LAUSCHEN_START": "1",
            }),
        )
        threading.Thread(target=self._mitlesen, daemon=True).start()

    def _mitlesen(self):
        # Jede Meldung endet mit den Regeln. Bis dahin gehört alles zu
        # einer Benachrichtigung.
        block = []
        for zeile in self.prozess.stdout:
            block.append(zeile)
            if zeile.startswith("Zum Umgang damit"):
                text = "".join(block)
                self.meldungen.append((time.time(), text))
                self.protokoll(f"{self.person}: Benachrichtigung vom Lauscher")
                block = []

    def warte_auf_meldung(self, muster, seit, frist=40):
        ende = time.time() + frist
        while time.time() < ende:
            for zeit, text in self.meldungen:
                if zeit >= seit and re.search(muster, text):
                    return zeit, text
            time.sleep(0.2)
        return None, ""

    def lauscher_lebt(self):
        ergebnis = subprocess.run(
            # Die Kommandozeile des Python-Prozesses selbst, ohne Anführungszeichen.
            ["pgrep", "-f", f"lauschen.py {self.projekt}"],
            capture_output=True, text=True,
        )
        return bool(ergebnis.stdout.strip())

    def beenden(self):
        if self.prozess and self.prozess.poll() is None:
            self.prozess.kill()
            self.prozess.wait(timeout=10)


def befehl_aus(text, muster):
    """Holt die Befehlszeile aus einer Meldung, wie Claude sie lesen würde."""
    for zeile in text.splitlines():
        if muster in zeile:
            treffer = re.search(r"`([^`]*" + re.escape(muster) + r"[^`]*)`", zeile)
            return treffer.group(1) if treffer else zeile.strip()
    raise AssertionError(f"Kein Befehl mit '{muster}' in:\n{text}")


def ablauf(basis: Path, ausgabe=print):
    """
    Spielt den Ablauf durch. Rückgabe: Liste von (schritt, ok, detail).
    """
    ergebnisse = []
    beginn = time.time()

    def protokoll(text):
        ausgabe(f"{time.time() - beginn:6.1f}s  {text}")

    def pruefe(schritt, ok, detail=""):
        ergebnisse.append((schritt, bool(ok), detail))
        protokoll(f"{'OK  ' if ok else 'FEHLT'} {schritt}" + (f"  ({detail})" if detail else ""))

    team = TeamUmgebung(basis)
    team.anzeigenamen.update({"Lars": "Lars Becker", "Max": "Max Mustermann"})
    for person in ("Lars", "Max"):
        team.person_anlegen(person)
    (team.projekte["Lars"] / "shared").mkdir()
    (team.projekte["Lars"] / "shared" / "models.py").write_text(
        "class Order:\n    total: float\n", encoding="utf-8")
    git(["add", "-A"], cwd=team.projekte["Lars"])
    git(["commit", "-qm", "Modell"], cwd=team.projekte["Lars"])
    git(["push", "-q"], cwd=team.projekte["Lars"])
    git(["pull", "-q"], cwd=team.projekte["Max"])
    for person in ("Lars", "Max"):
        einrichtung = team.setup(person)
        if einrichtung.returncode != 0:
            raise AssertionError(einrichtung.stderr)

    lars = Sitzung(team, "Lars", protokoll)
    max_ = Sitzung(team, "Max", protokoll)
    try:
        protokoll("Lars öffnet eine Session")
        kontext = lars.start().get("additionalContext", "")
        pruefe("Lars bekommt die Regeln zur Zusammenarbeit, obwohl der Channel leer ist",
               "Zusammenarbeit" in kontext and "/ask" in kontext)
        lars.lauscher_starten()

        protokoll("Lars bearbeitet shared/models.py")
        vorher = lars.edit("shared/models.py", "class Order:\n    total_cents: int\n")
        pruefe("Kein Hinweis bei einer freien Datei", not vorher)
        lars.stop()

        protokoll("Max öffnet eine Session")
        kontext = max_.start().get("additionalContext", "")
        pruefe("Max sieht beim Start, dass Lars arbeitet", "lars-becker" in kontext)
        max_.lauscher_starten()

        protokoll("Max will an shared/models.py")
        vorher = max_.edit("shared/models.py", "class Order:\n    def betrag_anzeige(self): ...\n")
        grund = vorher.get("permissionDecisionReason", "")
        pruefe("Der erste Edit wird angehalten, bevor er passiert",
               vorher.get("permissionDecision") == "deny"
               and "total: float" in (max_.projekt / "shared" / "models.py").read_text())
        pruefe("Die Begründung nennt Lars und einen ausführbaren Befehl",
               "lars-becker" in grund and "team_sync.py" in grund
               and "CLAUDE_PLUGIN_ROOT" not in grund)

        protokoll("Max führt den Befehl aus der Begründung aus")
        befehl = befehl_aus(grund, " anfrage ").replace(
            "<was du vorhast>", "Ich will betrag_anzeige() an Order ergänzen")
        gestellt = time.time()
        antwort = max_.shell(befehl)
        pruefe("Die Anfrage ist abgelegt", "abgelegt" in antwort)

        zeit, meldung = lars.warte_auf_meldung(r"max-mustermann will an `shared/models.py`", gestellt)
        pruefe("Lars wird geweckt, während seine Session wartet",
               zeit, f"nach {zeit - gestellt:.1f}s" if zeit else "keine Meldung")

        protokoll("Lars antwortet mit dem Befehl aus der Meldung")
        befehl = befehl_aus(meldung, " answer --id ")
        befehl = befehl.replace('--text "..."', '--text "Ich habe nur total zu total_cents '
                                                  'umbenannt. Ergänze betrag_anzeige() ruhig, '
                                                  'rechne mit total_cents in Cent."')
        beantwortet = time.time()
        lars.shell(befehl)

        zeit, meldung = max_.warte_auf_meldung(r"Antwort von lars-becker", beantwortet)
        pruefe("Max bekommt die Antwort, ohne etwas zu tun",
               zeit, f"nach {zeit - beantwortet:.1f}s" if zeit else "keine Meldung")
        pruefe("Die Antwort steht in der Meldung", "total_cents in Cent" in meldung)

        protokoll("Max versucht den Edit erneut")
        vorher = max_.edit("shared/models.py",
                           "class Order:\n    total_cents: int\n    def betrag_anzeige(self): ...\n")
        pruefe("Der zweite Versuch geht durch und erinnert an die Antwort",
               vorher.get("permissionDecision") is None
               and "beantwortet" in vorher.get("additionalContext", ""))

        protokoll("Lars committet, pusht und schreibt Max")
        git(["commit", "-qam", "Betrag in Cent"], cwd=lars.projekt)
        git(["push", "-q"], cwd=lars.projekt)
        gesendet = time.time()
        # So, wie der Slash-Command /post es Claude vorgibt.
        lars.shell(f'"{sys.executable}" "{SCRIPTS / "team_sync.py"}" post '
                   f'--text "@max total_cents ist auf main, du kannst pullen."')
        zeit, meldung = max_.warte_auf_meldung(r"total_cents ist auf main", gesendet)
        pruefe("Die Nachricht weckt Max",
               zeit, f"nach {zeit - gesendet:.1f}s" if zeit else "keine Meldung")

        protokoll("Max tippt etwas und beendet einen Zug")
        doppelt = max_.eingabe().get("additionalContext", "") + max_.stop().get("additionalContext", "")
        pruefe("Nichts kommt doppelt", "total_cents ist auf main" not in doppelt
               and "Antwort von lars-becker" not in doppelt)
        nachrichten_an_lars = [t for _, t in lars.meldungen if "Nachricht an dich" in t]
        pruefe("Lars bekommt seine eigene Nachricht nicht zurück", not nachrichten_an_lars)

        protokoll("Lars beendet seine Session mit /exit")
        dauer = lars.ende()
        pruefe("Der SessionEnd-Hook ist in Claudes 1,5 Sekunden fertig", dauer < 1.5, f"{dauer:.2f}s")
        frist = time.time() + 30
        while time.time() < frist:
            log = git(["log", "--format=%s", "team-channel"], cwd=team.remote).stdout
            if "freigegeben: lars-becker - alle" in log:
                break
            time.sleep(0.5)
        pruefe("Lars' Reservierungen sind danach frei", "freigegeben: lars-becker - alle" in log)

        frist = time.time() + 20
        while time.time() < frist and lars.lauscher_lebt():
            time.sleep(0.5)
        pruefe("Lars' Lauscher endet mit der Session", not lars.lauscher_lebt())

        protokoll("Max wartet auf den nächsten Durchlauf seines Lauschers")
        frist = time.time() + 3 * LAUSCH_SEKUNDEN
        frei = False
        while time.time() < frist and not frei:
            time.sleep(1)
            vorher = max_.edit("shared/models.py",
                               "class Order:\n    total_cents: int\n    def betrag_anzeige(self): return ''\n")
            frei = not vorher
        pruefe("Danach bearbeitet Max die Datei ohne Hinweis", frei)
    finally:
        lars.beenden()
        max_.beenden()
        # Ohne ihre Sitzung enden die Lauscher von selbst. Darauf warten,
        # damit keiner in einen schon gelöschten Testordner weiterläuft.
        for sitzung in (lars, max_):
            frist = time.time() + 15
            while time.time() < frist and sitzung.lauscher_lebt():
                time.sleep(0.5)
            if sitzung.lauscher_lebt():
                subprocess.run(["pkill", "-f", f"lauschen.py {sitzung.projekt}"])
                pruefe(f"{sitzung.person}s Lauscher endet ohne Nachhilfe", False)

    return ergebnisse


def main():
    if os.name == "nt" or not all(shutil.which(b) for b in ("bash", "sh", "pgrep")):
        print("Das Szenario braucht bash und sh.")
        return 0
    with tempfile.TemporaryDirectory(prefix="team-sync-szenario-") as tmp:
        ergebnisse = ablauf(Path(tmp).resolve())
    fehlt = [s for s, ok, _ in ergebnisse if not ok]
    print()
    print(f"{len(ergebnisse) - len(fehlt)} von {len(ergebnisse)} Schritten in Ordnung.")
    for schritt in fehlt:
        print(f"  FEHLT: {schritt}")
    return 1 if fehlt else 0


if __name__ == "__main__":
    sys.exit(main())
