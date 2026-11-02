"""
Der Lauscher: hält den Channel im Hintergrund aktuell und meldet sich,
sobald etwas für diese Session ankommt.

Die Idee kommt vom Hackathon-Board. Dort lässt jeder Agent den Befehl
'tools/board wait' im Hintergrund laufen. Der kehrt zurück, sobald
jemand etwas postet, und weckt damit den Agenten, auch wenn der gerade
auf seinen Menschen wartet. Erst dadurch können sich zwei Agenten
Arbeit übergeben, ohne dass jemand dazwischen tippt.

Bis 0.4 hatte team-sync das nicht. Gelesen wurde nur nach einer Antwort
von Claude, und eine Session, die auf Eingabe wartete, war taub.

Hier läuft dasselbe auf zwei Wegen:

    Monitor   Claude Code startet scripts/lauschen.py mit jeder Session
              als Plugin-Monitor. Was er ausgibt, kommt bei Claude als
              Benachrichtigung an. Anders als beim Board muss Claude
              nichts selbst starten oder nach jedem Wecken neu anstoßen.
    warten    'team_sync.py warten' kehrt bei der ersten Meldung zurück,
              wie 'tools/board wait'. Für andere Agenten, für Skripte
              und für alle, bei denen Monitore nicht laufen.

Ein Durchlauf kostet einen 'git ls-remote', also eine Anfrage an das
Remote ohne Datenübertragung. Gezogen wird nur, wenn sich der Branch
dort tatsächlich bewegt hat.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from . import empfang
from .channel import (
    CHANNEL_BRANCH,
    channel_is_ready,
    get_agent_name,
    lauscher_melden,
    pull_gesperrt,
    pull_merken,
    run_git,
)

# Abstand zwischen zwei Blicken auf das Remote (Sekunden). Dreißig bis
# sechzig sind für ein Team von wenigen Leuten unkritisch, auch gegen
# GitHub, denn ls-remote überträgt nichts außer einer Handvoll Zeilen.
INTERVALL = max(5, int(os.environ.get("TEAM_SYNC_LAUSCHEN_SECONDS", "45")))

# Wartezeit vor dem ersten Durchlauf. Der Monitor startet zusammen mit
# dem SessionStart-Hook. Liefe er sofort los, könnte er melden, was der
# Startkontext gleich noch einmal zeigt.
STARTVERZOEGERUNG = int(os.environ.get("TEAM_SYNC_LAUSCHEN_START", "20"))

# Längste Pause nach wiederholten Netzwerkfehlern.
MAX_PAUSE = 600


def abgeschaltet() -> bool:
    wert = (os.environ.get("TEAM_SYNC_LAUSCHEN") or "").strip().lower()
    return wert in ("0", "aus", "off", "nein", "no", "false")


def remote_stand(channel_dir: Path):
    """Der Commit, auf dem der Channel-Branch im Remote steht, oder None."""
    ok, out = run_git(
        ["ls-remote", "origin", f"refs/heads/{CHANNEL_BRANCH}"],
        cwd=channel_dir,
        timeout=20,
    )
    if not ok or not out:
        return None
    return out.split()[0]


def lokaler_stand(channel_dir: Path):
    """Der zuletzt geholte Stand des Remote-Branches."""
    ok, out = run_git(
        ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{CHANNEL_BRANCH}"],
        cwd=channel_dir,
    )
    return out if ok and out else None


def ein_durchlauf(project_dir: Path, channel_dir: Path, me: str):
    """
    Ein Blick auf das Remote, gefolgt vom lokalen Rückkanal.

    Rückgabe: (text, netz_ok). text ist leer, wenn nichts anliegt.
    """
    remote = remote_stand(channel_dir)
    netz_ok = remote is not None

    if netz_ok and remote != lokaler_stand(channel_dir):
        if pull_gesperrt(channel_dir, timeout=30):
            pull_merken(project_dir)

    # Gelesen wird auch ohne Änderung am Remote. Ein schreibender Hook
    # kann inzwischen gezogen haben, und was dabei hereinkam, soll nicht
    # erst mit der nächsten Eingabe auffallen.
    return empfang.neuigkeiten(channel_dir, project_dir, me), netz_ok


def _elternprozess_von(pid: int):
    """Der Elternprozess eines anderen Prozesses, oder None."""
    try:
        # Linux: das vierte Feld in /proc/<pid>/stat. Der Name in
        # Klammern kann Leerzeichen enthalten, deshalb nach der
        # schließenden Klammer trennen.
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        return int(stat.rsplit(")", 1)[1].split()[1])
    except Exception:
        pass
    try:
        # macOS und andere ohne /proc.
        ergebnis = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
        wert = (ergebnis.stdout or "").strip()
        return int(wert) if wert.isdigit() else None
    except Exception:
        return None


def _lebt(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Gibt es, gehört aber jemand anderem. Dann lebt er.
        return True
    except Exception:
        return True
    # Ein beendeter Prozess, den sein Elternprozess noch nicht abgeholt
    # hat, antwortet auf das Signal, ist aber tot. In der Simulation lief
    # der Lauscher deshalb weiter, bis die Regie ihre Kinder abräumte.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        return stat.rsplit(")", 1)[1].split()[0] != "Z"
    except Exception:
        return True


class _Elternwaechter:
    """
    Merkt, wenn die Session, die den Lauscher gestartet hat, weg ist.

    Claude Code beendet seine Monitore mit der Session. Stürzt es ab oder
    wird es hart beendet, bleibt der Lauscher zurück. Den direkten
    Elternprozess zu beobachten reicht dabei nicht: Claude Code startet
    den Monitor über eine Shell, und diese Shell überlebt den Absturz.
    Im Test mit einer echten Sitzung lief der Lauscher genau so weiter.

    Deshalb merkt er sich beim Start die ersten beiden Vorfahren, also
    Shell und Claude Code, und endet, sobald einer davon verschwunden
    ist. Nicht mehr als zwei: Ein Startprogramm weiter oben darf sich
    beenden, ohne dass die Session damit endet. Unter
    Windows geht das mit der Standardbibliothek nicht gefahrlos, denn
    os.kill(pid, 0) sendet dort ein Strg+C. Dort endet ein Lauscher
    spätestens nach einem Tag, länger läuft kaum eine Session am Stück.
    """

    WINDOWS_HOECHSTENS = 24 * 3600
    TIEFE = 2

    def __init__(self):
        self.beginn = time.time()
        self.vorfahren = []
        if os.name == "nt" or not hasattr(os, "getppid"):
            return
        pid = os.getppid()
        while pid and pid > 1 and len(self.vorfahren) < self.TIEFE:
            self.vorfahren.append(pid)
            pid = _elternprozess_von(pid)

    def verwaist(self) -> bool:
        if os.name == "nt":
            return time.time() - self.beginn > self.WINDOWS_HOECHSTENS
        return any(not _lebt(pid) for pid in self.vorfahren)


def _schlafen(sekunden, waechter, schlafen):
    """
    Schläft in kurzen Abschnitten und bricht ab, wenn die Session weg ist.

    Mit einem einzigen langen Schlaf würde ein verwaister Lauscher nach
    einem Absturz noch Minuten weiterlaufen.
    """
    rest = sekunden
    while rest > 0:
        if waechter.verwaist():
            return False
        abschnitt = min(5, rest)
        schlafen(abschnitt)
        rest -= abschnitt
    return not waechter.verwaist()


def schleife(project_dir: Path, channel_dir: Path, intervall=INTERVALL, einmal=False,
             timeout=0, ausgabe=None, startverzoegerung=0, schlafen=time.sleep):
    """
    Die Hauptschleife.

    einmal=True kehrt bei der ersten Meldung zurück (team_sync.py warten).
    Sonst läuft sie, bis der Elternprozess weg ist.

    Rückgabe: 0 nach einer Meldung im Modus einmal, 124 bei Ablauf von
    timeout, 0 wenn der Elternprozess weg ist.
    """
    ausgabe = ausgabe or _ausgeben
    me = get_agent_name(project_dir)
    waechter = _Elternwaechter()
    beginn = time.time()
    pause = intervall

    if startverzoegerung and not _schlafen(startverzoegerung, waechter, schlafen):
        return 0

    while True:
        if waechter.verwaist():
            return 0

        text = ""
        try:
            text, netz_ok = ein_durchlauf(project_dir, channel_dir, me)
            # Nach Netzwerkfehlern seltener fragen, bis zu zehn Minuten.
            # Ein Laptop ohne Netz soll nicht alle halbe Minute ins Leere
            # laufen, und nach der Rückkehr reicht ein normaler Takt.
            pause = intervall if netz_ok else min(pause * 2, MAX_PAUSE)
            lauscher_melden(project_dir)
        except Exception as exc:
            print(f"team-sync: Lauscher-Durchlauf fehlgeschlagen: {exc}", file=sys.stderr)

        if text:
            ausgabe(text)
            if einmal:
                return 0

        if timeout and time.time() - beginn >= timeout:
            return 124

        if not _schlafen(pause, waechter, schlafen):
            return 0


def _ausgeben(text: str):
    # Alles in einem Zug und sofort geleert. Claude Code fasst Zeilen,
    # die innerhalb von 200 ms kommen, zu einer Benachrichtigung
    # zusammen. Gepuffert käme die Meldung erst Minuten später an.
    sys.stdout.write(text.rstrip() + "\n")
    sys.stdout.flush()


def ruhen(schlafen=time.sleep):
    """
    Schläft, ohne etwas zu tun, bis der Elternprozess weg ist.

    Für Projekte ohne Channel und für einen abgeschalteten Lauscher.
    Sich einfach zu beenden wäre naheliegend, aber Claude Code meldet
    das Ende eines Monitors in der Session, und das hieße in jedem
    Projekt ohne Channel eine sinnlose Meldung pro Session.
    """
    waechter = _Elternwaechter()
    while _schlafen(60, waechter, schlafen):
        pass
    return 0


def bereit(channel_dir: Path) -> bool:
    return channel_is_ready(channel_dir)
