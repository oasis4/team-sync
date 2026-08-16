"""
Gemeinsame Hilfsfunktionen für alle team-sync Skripte.

Grundidee: Neben dem eigentlichen Projekt-Repo liegt ein zweiter,
lokaler Checkout desselben Repos auf dem Branch "team-channel".
Das ist ein git worktree, siehe scripts/setup_channel.py. Darin:

  status/     eine Datei pro Person, aktueller Stand
  questions/  eine Datei pro Frage, wird um eine Antwort ergänzt
  decisions/  eine Datei pro Architekturentscheidung

Zwei Regeln, die für alles hier gelten:

1. Kein Fehler in diesen Funktionen darf jemals eine Claude-Code-Session
   blockieren. Alles, was schiefgehen kann, gibt einen Rückgabewert
   statt einer Exception.
2. Keine externen Abhängigkeiten. Nur die Standardbibliothek, damit das
   Plugin auf jedem Rechner ohne Installation läuft.
"""

import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

# Der Branch, auf dem der Team-Channel liegt.
CHANNEL_BRANCH = os.environ.get("TEAM_SYNC_BRANCH", "team-channel")

# Unterordner im Channel.
SUBDIRS = ("status", "questions", "decisions")

# Ab wann ein Status als veraltet gilt (Stunden).
STALE_AFTER_HOURS = int(os.environ.get("TEAM_SYNC_STALE_HOURS", "48"))

_UMLAUTE = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "ß": "ss", "æ": "ae", "ø": "oe", "å": "aa",
}


def setup_stdio():
    """
    Erzwingt UTF-8 auf allen drei Standardkanälen.

    Ohne das bricht ein print() mit Umlauten auf einer Windows-Konsole
    mit cp1252 als UnicodeEncodeError ab, und ein Hook, der abbricht,
    schreibt keinen Status mehr.

    Die Eingabe braucht dieselbe Behandlung: Übergibt Claude eine Frage
    über die Standardeingabe, wird sie als UTF-8 geschickt. Wird sie
    als cp1252 gelesen, kommt aus "größer" ein "grÃ¶ÃŸer" an, und das
    steht dann dauerhaft so im Channel.
    """
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def eprint(*args):
    print(*args, file=sys.stderr)


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _git_env():
    """
    Umgebung für alle git-Aufrufe.

    Entscheidend ist GIT_TERMINAL_PROMPT=0: Fragt git beim Push nach
    Zugangsdaten, gibt es in einem Hook keine Konsole, an der jemand
    antworten könnte. Ohne diese Sperre wartet der Aufruf bis zum
    Timeout, und die Session steht so lange still.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("GCM_INTERACTIVE", "never")
    return env


def run_git(args, cwd, timeout=15):
    """
    Führt einen git-Befehl aus und gibt (erfolgreich, stdout) zurück.

    Wirft nie eine Exception. Ein fehlendes git, ein kaputtes Repo oder
    ein hängender Netzwerkaufruf liefern einfach (False, "").
    """
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            # Ohne das erbt git die Standardeingabe des Hooks und
            # könnte darauf warten, dass jemand etwas eintippt.
            stdin=subprocess.DEVNULL,
            env=_git_env(),
        )
        return result.returncode == 0, (result.stdout or "").strip()
    except Exception:
        return False, ""


def get_project_dir() -> Path:
    """Verzeichnis des eigentlichen Projekt-Repos."""
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        return Path(raw).resolve()
    except Exception:
        return Path(os.getcwd()).resolve()


def get_git_dir(project_dir: Path):
    """
    Absoluter Pfad zum .git-Verzeichnis des Projekts.

    Wichtig: In einem Worktree ist .git eine Datei, kein Verzeichnis.
    Wer dort blind einen Pfad zusammenbaut, schreibt ins Leere.
    """
    ok, out = run_git(["rev-parse", "--absolute-git-dir"], cwd=project_dir)
    if ok and out:
        return Path(out)
    fallback = project_dir / ".git"
    return fallback if fallback.is_dir() else None


def get_current_branch(project_dir: Path) -> str:
    ok, branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_dir)
    return branch if ok and branch else "unbekannt"


def list_worktrees(project_dir: Path):
    """Gibt [(pfad, branch), ...] aller Worktrees des Repos zurück."""
    ok, out = run_git(["worktree", "list", "--porcelain"], cwd=project_dir)
    if not ok or not out:
        return []

    worktrees = []
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and path:
            branch = line[len("branch "):].strip()
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
            worktrees.append((path, branch))
            path = None
    return worktrees


def get_channel_dir(project_dir: Path) -> Path:
    """
    Ermittelt das Channel-Verzeichnis, in dieser Reihenfolge:

    1. TEAM_SYNC_CHANNEL_DIR, falls gesetzt.
    2. Der Worktree des Repos, der auf dem Channel-Branch steht. Das ist
       der zuverlässige Weg, denn er findet den Ordner auch dann, wenn
       er umbenannt oder woanders hin gelegt wurde.
    3. Die Namenskonvention <projektname>-channel als Geschwisterordner.

    Gibt immer einen Pfad zurück, auch wenn dort nichts existiert. Ob
    der Channel wirklich da ist, prüft channel_is_ready().
    """
    override = os.environ.get("TEAM_SYNC_CHANNEL_DIR")
    if override:
        try:
            return Path(override).expanduser().resolve()
        except Exception:
            pass

    for path, branch in list_worktrees(project_dir):
        if branch == CHANNEL_BRANCH:
            try:
                return Path(path).resolve()
            except Exception:
                return Path(path)

    return project_dir.parent / f"{project_dir.name}-channel"


def channel_is_ready(channel_dir: Path) -> bool:
    """Existiert der Channel und ist er ein Git-Arbeitsverzeichnis?"""
    try:
        if not channel_dir.is_dir():
            return False
    except Exception:
        return False
    ok, out = run_git(["rev-parse", "--is-inside-work-tree"], cwd=channel_dir)
    return ok and out == "true"


def setup_hint(channel_dir: Path) -> str:
    return (
        f"Kein team-channel gefunden (erwartet unter {channel_dir}).\n"
        "Einmaliges Setup im Projekt-Repo:\n"
        "    python3 <plugin>/scripts/setup_channel.py"
    )


# ---------------------------------------------------------------------------
# Sperre gegen parallele Sessions
# ---------------------------------------------------------------------------


class ChannelLock:
    """
    Einfache Dateisperre für den Channel-Worktree.

    Genau der Fall, für den dieses Plugin gebaut ist, erzeugt das
    Problem: mehrere Claude-Sessions am selben Repo. Schreiben zwei
    davon gleichzeitig in denselben Worktree, kollidieren sie an
    git's index.lock und eine der beiden verliert ihren Status.

    Wird als Kontextmanager benutzt und ist bewusst nachgiebig: Wer die
    Sperre nicht bekommt, wartet kurz und gibt dann auf, statt einen
    Hook hängen zu lassen. Eine verwaiste Sperre (abgestürzter Prozess)
    wird nach stale_seconds ignoriert.
    """

    def __init__(self, channel_dir: Path, timeout=8.0, stale_seconds=120.0):
        # Die Sperrdatei gehört ins Git-Verzeichnis, nicht in den
        # Arbeitsbaum. Läge sie im Channel, würde das folgende
        # 'git add -A' sie mitcommitten, und zwei Personen mit jeweils
        # eigener Sperrdatei bekämen bei jedem Rebase einen Konflikt in
        # genau der Datei, die Konflikte verhindern soll.
        git_dir = get_git_dir(channel_dir)
        basis = git_dir if git_dir is not None else channel_dir
        self.lock_path = basis / "team-sync.lock"
        self.timeout = timeout
        self.stale_seconds = stale_seconds
        self.acquired = False

    def __enter__(self):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._try_acquire():
                self.acquired = True
                return self
            self._clear_if_stale()
            time.sleep(0.25)
        return self

    def __exit__(self, *exc_info):
        if self.acquired:
            try:
                self.lock_path.unlink()
            except Exception:
                pass
        return False

    def _try_acquire(self) -> bool:
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except Exception:
            # Kein Schreibrecht o. ä.: lieber ohne Sperre weitermachen,
            # als die Session zu blockieren.
            return True
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        except Exception:
            pass
        finally:
            os.close(fd)
        return True

    def _clear_if_stale(self):
        try:
            age = time.time() - self.lock_path.stat().st_mtime
            if age > self.stale_seconds:
                self.lock_path.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Namen
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """
    Macht aus einem Namen einen dateisystemtauglichen Bezeichner.

    Umlaute werden ausgeschrieben, alles andere Nicht-ASCII wird
    transliteriert. "Jörg Müller" wird zu "joerg-mueller", nicht zu
    "j-rg-m-ller".
    """
    if not text:
        return "unbekannt"

    text = text.strip()
    for src, dst in _UMLAUTE.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unbekannt"


def get_agent_name(project_dir: Path) -> str:
    """
    Stabiler Name der aktuellen Person.

    Überschreibbar per TEAM_AGENT_NAME, sonst aus git config user.name.
    Der Wert ist der Dateiname im Channel, er muss also im ganzen Team
    eindeutig und über die Zeit stabil sein.
    """
    override = os.environ.get("TEAM_AGENT_NAME")
    if override:
        return slugify(override)

    ok, name = run_git(["config", "user.name"], cwd=project_dir)
    if ok and name:
        return slugify(name)

    return "unbekannt"


# ---------------------------------------------------------------------------
# Channel lesen und schreiben
# ---------------------------------------------------------------------------


def ensure_subdirs(channel_dir: Path):
    for sub in SUBDIRS:
        try:
            (channel_dir / sub).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def pull_channel(channel_dir: Path, timeout=30) -> bool:
    """
    Holt den aktuellen Stand.

    Rebase statt Merge, damit keine Merge-Commits im Channel landen.
    Autostash, damit ein halb geschriebener Status den Pull nicht
    blockiert. Bleibt ein Rebase im Konflikt stecken, wird er
    abgebrochen, statt den Worktree in einem kaputten Zustand
    zurückzulassen.

    Der Timeout ist knapp gehalten und beim Sessionstart noch knapper:
    Ein hängender Netzwerkaufruf darf den Start einer Session nicht
    spürbar verzögern. Dann wird eben der letzte lokale Stand gelesen.
    """
    if not channel_is_ready(channel_dir):
        return False

    ok, _ = run_git(
        ["pull", "--rebase", "--autostash", "--quiet"], cwd=channel_dir, timeout=timeout
    )
    if not ok:
        run_git(["rebase", "--abort"], cwd=channel_dir)
    return ok


def has_unpushed_commits(channel_dir: Path) -> bool:
    ok, out = run_git(["rev-list", "--count", "@{upstream}..HEAD"], cwd=channel_dir)
    if not ok:
        # Kein Upstream: pushen versuchen und git entscheiden lassen.
        return True
    try:
        return int(out) > 0
    except ValueError:
        return True


def push_channel(channel_dir: Path, message: str, retries=3) -> bool:
    """
    Committet alle Änderungen im Channel und pusht sie.

    Der Prototyp hat hier still verloren: schiebt jemand zwischen Pull
    und Push etwas dazwischen, wird der Push abgelehnt, und der eigene
    Status liegt bis zum nächsten Mal nur lokal herum. Deshalb bei
    Ablehnung rebasen und erneut versuchen.
    """
    if not channel_is_ready(channel_dir):
        return False

    run_git(["add", "-A"], cwd=channel_dir)
    # Kein Fehler, wenn es nichts zu committen gab.
    run_git(["commit", "-m", message], cwd=channel_dir)

    if not has_unpushed_commits(channel_dir):
        return True

    for attempt in range(retries):
        ok, _ = run_git(["push", "--quiet"], cwd=channel_dir, timeout=30)
        if ok:
            return True
        if attempt < retries - 1:
            if not pull_channel(channel_dir):
                break
    return False


def write_and_push(channel_dir: Path, rel_path: str, content: str, message: str) -> bool:
    """
    Der vollständige Schreibvorgang: sperren, pullen, schreiben, pushen.

    Rückgabe True heißt, die Datei ist geschrieben und liegt beim
    Remote. False heißt, sie ist geschrieben, aber noch nicht gepusht,
    oder es ging gar nichts. Das unterscheidet der Aufrufer über
    file_written(), wenn es ihn interessiert.
    """
    with ChannelLock(channel_dir):
        ensure_subdirs(channel_dir)
        pull_channel(channel_dir)

        target = channel_dir / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(target, content)
        except Exception as exc:
            eprint(f"team-sync: {rel_path} konnte nicht geschrieben werden: {exc}")
            return False

        return push_channel(channel_dir, message)


def write_text_lf(path: Path, content: str):
    """
    Schreibt eine Datei als UTF-8 mit Unix-Zeilenenden.

    Nicht über die gleichnamige Methode von Path mit dem Argument für
    Zeilenenden: die kennt es erst ab Python 3.10. Im Team laufen
    verschiedene Python-Versionen, und unter 3.9 stieg das Setup damit
    mit einem TypeError aus.

    Feste Zeilenenden sind hier wichtig, weil derselbe Channel von
    Windows- und Linux-Rechnern beschrieben wird. Ohne sie zeigt jeder
    Wechsel die ganze Datei als geändert an.
    """
    with open(str(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def list_files_sorted(folder: Path):
    try:
        if not folder.is_dir():
            return []
        return sorted(folder.glob("*.md"))
    except Exception:
        return []


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Drosselung der automatischen Zwischenstände
# ---------------------------------------------------------------------------


def get_throttle_marker(project_dir: Path):
    """
    Markerdatei für den Zeitpunkt des letzten Zwischenstands.

    Liegt im .git-Verzeichnis des Projekts, wird also nie mit
    synchronisiert. Sie hält fest, was auf diesem einen Rechner zuletzt
    passiert ist, und geht niemanden sonst etwas an.
    """
    git_dir = get_git_dir(project_dir)
    if git_dir is None:
        return None
    return git_dir / "team-sync-throttle"


def should_checkpoint(project_dir: Path, min_interval_seconds: int) -> bool:
    marker = get_throttle_marker(project_dir)
    if marker is None or not marker.exists():
        return True
    try:
        return (time.time() - marker.stat().st_mtime) >= min_interval_seconds
    except Exception:
        return True


def touch_throttle(project_dir: Path):
    marker = get_throttle_marker(project_dir)
    if marker is None:
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Zeit
# ---------------------------------------------------------------------------


def now_stamp() -> str:
    """Zeitstempel für die Anzeige."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def now_id() -> str:
    """Zeitstempel für Dateinamen, sortiert sich chronologisch."""
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def parse_stamp(value: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def describe_age(stamp: str) -> str:
    """
    Wandelt einen Zeitstempel in eine lesbare Altersangabe um.

    Ein Status von vorgestern soll auf den ersten Blick als alt
    erkennbar sein, sonst plant jemand seinen Tag nach einer
    Information, die längst überholt ist.
    """
    parsed = parse_stamp(stamp)
    if parsed is None:
        return ""

    delta = datetime.now() - parsed
    if delta < timedelta(0):
        return "gerade eben"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return "vor wenigen Minuten" if minutes < 5 else f"vor {minutes} Minuten"
    hours = minutes // 60
    if hours < 24:
        return f"vor {hours} Stunde{'n' if hours != 1 else ''}"
    days = hours // 24
    return f"vor {days} Tag{'en' if days != 1 else ''}"


def is_stale(stamp: str) -> bool:
    parsed = parse_stamp(stamp)
    if parsed is None:
        return False
    return datetime.now() - parsed > timedelta(hours=STALE_AFTER_HOURS)
