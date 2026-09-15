#!/usr/bin/env python3
"""
Einmaliges Setup des Team-Channels. Führt jede Person einmal pro
Projekt aus, direkt im Projekt-Repo:

    python3 <plugin>/scripts/setup_channel.py

Ablauf:
  1. Existiert der Branch team-channel schon auf dem Remote, wird er
     als Worktree daneben ausgecheckt.
  2. Existiert er noch nicht, legt ihn die erste Person an: als
     verwaisten Branch ohne jede Verbindung zur Projekthistorie, mit
     leerer Ordnerstruktur.

Ergebnis ist ein Ordner <projekt>-channel neben dem Projektordner. Die
Hooks finden ihn danach von selbst.

Der Branch bleibt bewusst verwaist. Er enthält keine Zeile Code,
sondern nur Notizen, und soll nie in main gemergt werden. Ein
verwaister Branch macht das unmissverständlich und hält die
Projekthistorie sauber.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.channel import (
    CHANNEL_BRANCH,
    SUBDIRS,
    cache_verwerfen,
    run_git,
    setup_stdio,
    write_text_lf,
)

README_CHANNEL = """# Team-Channel

Dieser Branch enthält keinen Code.

Er trägt den geteilten Arbeitsstand des Teams: wer gerade woran
arbeitet, welche Fragen offen sind und welche Architekturentscheidungen
getroffen wurden. Geschrieben und gelesen wird das vom Plugin
[team-sync](https://github.com/oasis4/team-sync), aus Claude Code oder
aus Antigravity.

- `status/` eine Datei pro Person, automatisch aktualisiert
- `questions/` eine Datei pro Frage, angelegt mit `/ask`, beantwortet mit `/answer`
- `decisions/` eine Datei pro Entscheidung, angelegt mit `/decide`

Der Branch ist verwaist, er hat keinen gemeinsamen Vorfahren mit `main`.
Bitte nicht mergen. Von Hand editieren ist erlaubt, es sind ganz normale
Markdown-Dateien.
"""


def git(args, cwd, pflicht=True, leise=False):
    if not leise:
        print(f"  git {' '.join(args)}")
    ergebnis = subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if ergebnis.returncode != 0 and pflicht:
        print(f"\nFehlgeschlagen: git {' '.join(args)}", file=sys.stderr)
        if ergebnis.stderr:
            print(ergebnis.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return ergebnis.returncode == 0, (ergebnis.stdout or "").strip()


def abbruch(nachricht: str):
    print(f"\nAbbruch: {nachricht}", file=sys.stderr)
    sys.exit(1)


def remote_branch_existiert(project_dir) -> bool:
    ok, out = run_git(["ls-remote", "--heads", "origin", CHANNEL_BRANCH], cwd=project_dir)
    return ok and bool(out)


def lokaler_branch_existiert(project_dir) -> bool:
    ok, _ = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{CHANNEL_BRANCH}"],
        cwd=project_dir,
    )
    return ok


def lege_verwaisten_branch_an(project_dir):
    """
    Erzeugt den Channel-Branch als verwaisten Branch.

    Nicht über 'git worktree add --orphan': diese Option gibt es erst
    ab git 2.42, und im Team läuft nicht überall die neueste Version.
    Der Weg über commit-tree kommt ohne sie aus und funktioniert seit
    Jahren unverändert: einen leeren Baum anlegen, daraus einen Commit
    ohne Elternteil bauen, den Branch darauf zeigen lassen.
    """
    # mktree mit leerer Eingabe erzeugt den leeren Baum. Die Eingabe muss
    # ausdrücklich leer übergeben werden, sonst erbt git die Standardeingabe
    # des Aufrufers und wartet dort auf etwas, das nie kommt.
    ergebnis = subprocess.run(
        ["git", "mktree"], cwd=str(project_dir), input="",
        capture_output=True, text=True,
    )
    leerer_baum = (ergebnis.stdout or "").strip()
    if ergebnis.returncode != 0 or not leerer_baum:
        abbruch("Konnte keinen leeren Git-Baum erzeugen.")

    ergebnis = subprocess.run(
        ["git", "commit-tree", leerer_baum, "-m", "team-channel: Start"],
        cwd=str(project_dir), capture_output=True, text=True,
    )
    commit = (ergebnis.stdout or "").strip()
    if ergebnis.returncode != 0 or not commit:
        fehlertext = (ergebnis.stderr or "").strip()
        if "user.name" in fehlertext or "user.email" in fehlertext or "ident" in fehlertext:
            abbruch(
                "Git kennt deinen Namen noch nicht. Bitte einmalig setzen:\n"
                '  git config --global user.name "Dein Name"\n'
                '  git config --global user.email "du@example.com"'
            )
        abbruch(f"Konnte den Startcommit nicht erzeugen. {fehlertext}")

    git(["branch", CHANNEL_BRANCH, commit], cwd=project_dir)


def fuelle_struktur(channel_dir: Path):
    for unterordner in SUBDIRS:
        ziel = channel_dir / unterordner
        ziel.mkdir(parents=True, exist_ok=True)
        # Git speichert keine leeren Ordner, deshalb je eine Platzhalterdatei.
        (ziel / ".gitkeep").write_text("", encoding="utf-8")

    write_text_lf(channel_dir / "README.md", README_CHANNEL)

    # Die Skripte legen ihre Sperrdatei im Git-Verzeichnis ab. Der
    # Eintrag hier ist die zweite Sicherung: Nichts, was nur den
    # laufenden Prozess betrifft, darf je in den geteilten Branch
    # geraten, sonst streiten sich zwei Rechner um dieselbe Datei.
    write_text_lf(
        channel_dir / ".gitignore",
        "team-sync.lock\n"
        ".team-sync.lock\n"
        "team-sync-cache.json\n"
        "team-sync-postfach.json\n"
        "team-sync-dateien.json\n"
        "team-sync-antigravity.json\n",
    )


def main() -> int:
    setup_stdio()

    parser = argparse.ArgumentParser(description="Team-Channel einrichten")
    parser.add_argument(
        "--dir", help="Zielordner des Channels (Vorgabe: <projekt>-channel daneben)"
    )
    args = parser.parse_args()

    project_dir = Path.cwd().resolve()

    ok, toplevel = run_git(["rev-parse", "--show-toplevel"], cwd=project_dir)
    if not ok or not toplevel:
        abbruch(
            f"{project_dir} ist kein Git-Repository.\n"
            "Bitte das Skript im Projekt-Repo ausführen."
        )
    project_dir = Path(toplevel).resolve()

    channel_dir = (
        Path(args.dir).expanduser().resolve()
        if args.dir
        else project_dir.parent / f"{project_dir.name}-channel"
    )

    print(f"Projekt: {project_dir}")
    print(f"Channel: {channel_dir}")
    print()

    if channel_dir.exists():
        ok, _ = run_git(["rev-parse", "--is-inside-work-tree"], cwd=channel_dir)
        if ok:
            print("Der Channel ist bereits eingerichtet. Nichts zu tun.")
            print("Prüfen mit: python3 scripts/team_sync.py doctor")
            return 0
        abbruch(
            f"{channel_dir} existiert schon, ist aber kein Git-Arbeitsverzeichnis.\n"
            "Bitte den Ordner entfernen oder mit --dir einen anderen Ort wählen."
        )

    hat_remote, _ = run_git(["remote", "get-url", "origin"], cwd=project_dir)
    if not hat_remote:
        print(
            "Hinweis: Dieses Repo hat kein Remote 'origin'. Der Channel wird\n"
            "trotzdem angelegt, bleibt aber lokal, solange kein Remote da ist.\n"
        )

    if hat_remote:
        print("Hole den aktuellen Stand vom Remote ...")
        git(["fetch", "origin", "--quiet"], cwd=project_dir, pflicht=False)

    neu_angelegt = False

    if hat_remote and remote_branch_existiert(project_dir):
        print(f"Branch '{CHANNEL_BRANCH}' existiert auf dem Remote, checke ihn aus ...")
        if lokaler_branch_existiert(project_dir):
            git(["worktree", "add", str(channel_dir), CHANNEL_BRANCH], cwd=project_dir)
        else:
            git(
                ["worktree", "add", "--track", "-b", CHANNEL_BRANCH,
                 str(channel_dir), f"origin/{CHANNEL_BRANCH}"],
                cwd=project_dir,
            )
    elif lokaler_branch_existiert(project_dir):
        print(f"Branch '{CHANNEL_BRANCH}' existiert lokal, checke ihn aus ...")
        git(["worktree", "add", str(channel_dir), CHANNEL_BRANCH], cwd=project_dir)
    else:
        print(f"Branch '{CHANNEL_BRANCH}' existiert noch nicht, lege ihn an ...")
        lege_verwaisten_branch_an(project_dir)
        git(["worktree", "add", str(channel_dir), CHANNEL_BRANCH], cwd=project_dir)
        neu_angelegt = True

    if neu_angelegt:
        fuelle_struktur(channel_dir)
        git(["add", "-A"], cwd=channel_dir)
        git(["commit", "-m", "team-channel: Grundstruktur"], cwd=channel_dir)
        if hat_remote:
            print("Schiebe den neuen Branch zum Remote ...")
            git(["push", "-u", "origin", CHANNEL_BRANCH], cwd=channel_dir, pflicht=False)
    else:
        # Bei einem bestehenden Channel kann die Struktur unvollständig
        # sein, etwa wenn er mit einer älteren Version angelegt wurde.
        for unterordner in SUBDIRS:
            (channel_dir / unterordner).mkdir(parents=True, exist_ok=True)

    # Ein Cache aus der Zeit vor dem Setup zeigt auf einen Ort, an dem
    # nichts lag. Die Hooks würden ihn bis zu einer Minute weiterglauben.
    cache_verwerfen(project_dir)

    print()
    print("Fertig.")
    print(f"Der Channel liegt unter: {channel_dir}")
    print()
    print("Nächster Schritt: Plugin installieren, dann eine neue Claude-Code-Session")
    print("starten. Der Stand des Teams wird ab dann automatisch eingelesen.")
    print("Einrichtung prüfen: python3 scripts/team_sync.py doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
