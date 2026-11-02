"""
Regie für die echte Simulation: zwei interaktive Claude-Code-Sitzungen
arbeiten gleichzeitig am Testprojekt, jede mit dem Plugin.

Aufruf: python3 lauf.py <sim-ordner> <plugin-ordner> <modell> <maximal-sekunden>

Gedacht für eine abgeschottete Maschine, etwa eine Railway-Sandbox. Die
Anmeldung bei Anthropic kommt bevorzugt aus CLAUDE_CODE_OAUTH_TOKEN oder
ANTHROPIC_API_KEY in der Umgebung. Fehlen beide, wird die lokale
Anmeldedatei in einen eigenen Konfigurationsordner kopiert und am Ende
gelöscht. Alle anderen CLAUDE*-Variablen werden nicht vererbt, damit die
Testsitzungen nicht an eine laufende Session gebunden sind.

Die Sitzungen dürfen Dateien nur im eigenen Testprojekt bearbeiten und
in der Shell nur git und die team-sync-Kommandozeile benutzen. Alles
andere wird ohne Rückfrage abgelehnt.
"""

import fcntl
import json
import os
import pty
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

SIM = Path(sys.argv[1]).resolve()
PLUGIN = Path(sys.argv[2]).resolve()
MODELL = sys.argv[3]
MAXIMAL = int(sys.argv[4])
TEAM = SIM / "team"

# Anmeldung bei Anthropic, die an die Testsitzungen weitergereicht wird.
ANMELDE_VARIABLEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
ANMELDUNG_AUS_UMGEBUNG = any(os.environ.get(v) for v in ANMELDE_VARIABLEN)
REMOTE = TEAM / "remote.git"
LOG = SIM / "log"

AUFGABEN = {
    "lars": (
        "Ich bin Lars und mache das Backend in diesem Repo. Aufgabe: Die API "
        "soll den Bestellbetrag nicht mehr als Euro-Float im Feld `total` "
        "liefern, sondern als Ganzzahl in Cent im Feld `total_cents`. Stell "
        "dafür api/orders.py und shared/models.py um. Wenn alles passt, "
        "committe und pushe auf main. Max baut parallel das Frontend und "
        "hängt von diesem Format ab. "
        "Ich bin die nächste Stunde nicht erreichbar, arbeite selbstständig bis "
        "zum Ende. In der Shell darfst du hier nur git und die "
        "team-sync-Kommandozeile benutzen, Dateien bearbeitest du mit den "
        "Datei-Werkzeugen."
    ),
    "max": (
        "Ich bin Max und mache das Frontend in diesem Repo. Aufgabe: Baue in "
        "frontend/render.py eine Funktion format_order(order), die den "
        "Bestellbetrag als '12,34 €' ausgibt, und ergänze in shared/models.py "
        "an der Klasse Order eine Methode betrag_anzeige(), die diesen Text "
        "liefert. Lars stellt im Backend gerade das Betragsformat um, richte "
        "dich nach dem Format, das er festlegt. Committe und pushe auf main, "
        "wenn du fertig bist. "
        "Ich bin die nächste Stunde nicht erreichbar, arbeite selbstständig bis "
        "zum Ende. In der Shell darfst du hier nur git und die "
        "team-sync-Kommandozeile benutzen, Dateien bearbeitest du mit den "
        "Datei-Werkzeugen."
    ),
}


def protokoll(text):
    zeile = f"{time.strftime('%H:%M:%S')} {text}"
    print(zeile, flush=True)
    with open(LOG / "regie.log", "a", encoding="utf-8") as handle:
        handle.write(zeile + "\n")


def konfiguration(person):
    """Eigener Konfigurationsordner, Ersteinrichtung und Vertrauen gesetzt."""
    conf = SIM / f"conf-{person}"
    shutil.rmtree(conf, ignore_errors=True)
    conf.mkdir(parents=True)
    lokal = Path.home() / ".claude" / ".credentials.json"
    if not ANMELDUNG_AUS_UMGEBUNG and lokal.exists():
        ziel = conf / ".credentials.json"
        shutil.copy(lokal, ziel)
        os.chmod(ziel, 0o600)
    projekt = str(TEAM / person)
    (conf / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True,
        "theme": "dark",
        "numStartups": 5,
        "projects": {projekt: {"hasTrustDialogAccepted": True,
                               "hasCompletedProjectOnboarding": True}},
    }))
    # Eng gefasst: Dateien nur im eigenen Testprojekt, in der Shell nur
    # git und die team-sync-Kommandozeile. Alles andere wird ohne
    # Rückfrage abgelehnt (dontAsk), damit niemand an einem Dialog hängt.
    cli = f"{PLUGIN}/scripts/team_sync.py"
    git_befehle = ["status", "diff", "log", "add", "commit", "pull", "push",
                   "fetch", "rebase", "show", "stash"]
    (conf / "settings.json").write_text(json.dumps({
        "permissions": {
            "allow": [
                "Read", "Glob", "Grep",
                f"Edit(/{projekt}/**)", f"Write(/{projekt}/**)", f"MultiEdit(/{projekt}/**)",
                f'Bash(python3 "{cli}":*)', f"Bash(python3 {cli}:*)",
            ] + [f"Bash(git {b}:*)" for b in git_befehle],
            "defaultMode": "dontAsk",
        },
    }))
    return conf


class Sitzung:
    def __init__(self, person):
        self.person = person
        self.conf = konfiguration(person)
        self.rohlog = open(LOG / f"bildschirm-{person}.log", "ab")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE") or k in ANMELDE_VARIABLEN}
        env.update(
            CLAUDE_CONFIG_DIR=str(self.conf),
            TEAM_SYNC_LAUSCHEN_SECONDS="10",
            TEAM_SYNC_LAUSCHEN_START="5",
            TERM="xterm-256color",
        )
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(TEAM / person)
            os.execvpe("claude", [
                "claude", "--plugin-dir", str(PLUGIN), "--model", MODELL,
                AUFGABEN[person],
            ], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 180, 0, 0))
        self.laeuft = True
        threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self):
        while self.laeuft:
            try:
                daten = os.read(self.fd, 65536)
            except OSError:
                break
            if not daten:
                break
            self.rohlog.write(daten)
            self.rohlog.flush()

    def senden(self, text):
        try:
            os.write(self.fd, text.encode("utf-8"))
        except OSError:
            pass

    def transkripte(self):
        return sorted((self.conf / "projects").glob("*/*.jsonl"))

    def zuletzt_aktiv(self):
        zeiten = [p.stat().st_mtime for p in self.transkripte()]
        return max(zeiten) if zeiten else 0

    def lebt(self):
        try:
            return os.waitpid(self.pid, os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return False

    def beenden(self):
        self.laeuft = False
        try:
            os.kill(self.pid, 9)
        except Exception:
            pass
        try:
            os.waitpid(self.pid, 0)
        except Exception:
            pass


def remote_log(branch):
    ergebnis = subprocess.run(
        ["git", "log", "--format=%ad %s", "--date=format:%H:%M:%S", branch],
        cwd=REMOTE, capture_output=True, text=True,
    )
    return ergebnis.stdout


def main():
    shutil.rmtree(LOG, ignore_errors=True)
    LOG.mkdir()
    sitzungen = {}
    beginn = time.time()
    try:
        protokoll("Lars startet")
        sitzungen["lars"] = Sitzung("lars")

        frist = time.time() + 240
        while time.time() < frist:
            if "reserviert: lars-becker - shared/models.py" in remote_log("team-channel"):
                break
            time.sleep(2)
        protokoll("Lars hat shared/models.py reserviert" if time.time() < frist
                  else "Lars hat shared/models.py nach 240 s nicht reserviert, Max startet trotzdem")

        protokoll("Max startet")
        sitzungen["max"] = Sitzung("max")

        # Laufen lassen, bis beide eine Weile ruhig sind oder die Zeit um ist.
        ruhe = 150
        while time.time() - beginn < MAXIMAL:
            time.sleep(5)
            jetzt = time.time()
            ruhig = all(jetzt - s.zuletzt_aktiv() > ruhe for s in sitzungen.values())
            if ruhig and jetzt - beginn > 240:
                protokoll(f"Beide seit {ruhe} s ruhig")
                break
        else:
            protokoll("Zeitlimit erreicht")

        for sitzung in sitzungen.values():
            protokoll(f"{sitzung.person}: /exit")
            sitzung.senden("/exit\r")
        time.sleep(4)
        # Claude Code fragt nach, weil der Lauscher als Hintergrundarbeit
        # läuft. Enter wählt "Exit and stop tasks".
        for sitzung in sitzungen.values():
            sitzung.senden("\r")
        time.sleep(15)
        for sitzung in sitzungen.values():
            protokoll(f"{sitzung.person}: beendet sich selbst" if not sitzung.lebt()
                      else f"{sitzung.person}: läuft nach /exit noch")
    finally:
        for sitzung in sitzungen.values():
            sitzung.beenden()
        # Auf die abgelösten SessionEnd-Prozesse warten.
        frist = time.time() + 40
        while time.time() < frist:
            log = remote_log("team-channel")
            if all(f"freigegeben: {p} - alle" in log or f"reserviert: {p}" not in log
                   for p in ("lars-becker", "max-mustermann")):
                break
            time.sleep(2)
        for sitzung in sitzungen.values():
            ziel = sitzung.conf / ".credentials.json"
            if ziel.exists():
                ziel.unlink()
        protokoll(f"Ende nach {int(time.time() - beginn)} s")
        reste = subprocess.run(["pgrep", "-af", "scripts/lauschen.py"],
                               capture_output=True, text=True).stdout
        protokoll("Lauscher-Reste: " + (reste.strip() or "keine"))


if __name__ == "__main__":
    main()
