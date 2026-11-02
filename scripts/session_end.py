#!/usr/bin/env python3
"""
SessionEnd-Hook: schreibt den abschließenden Status und gibt alle
Reservierungen frei.

Feuert beim echten Beenden einer Session, also bei /clear, /exit oder
Logout. Anders als der Zwischenstand ist das hier nicht gedrosselt, ein
Sessionende ist immer eine Aktualisierung wert.

Bis 0.4 lief das direkt im Hook und kam praktisch nie an. Claude Code
gibt SessionEnd-Hooks nur 1,5 Sekunden, und ein Timeout aus einem
Plugin hebt diese Grenze nicht an. Pull, Schreiben, Push und ein
zweiter Push für die Freigabe dauern länger. Der Hook wurde abgebrochen,
der letzte Stand fehlte, und die Reservierungen blieben vier Stunden
stehen. Die anderen bekamen in dieser Zeit Warnungen vor jemandem, der
längst Feierabend hatte.

Jetzt startet der Hook die Arbeit als eigenständigen Prozess, der das
Ende von Claude Code überlebt, und kehrt sofort zurück. Mit
--vordergrund läuft alles direkt, so wie es der abgelöste Prozess tut.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

VORDERGRUND = "--vordergrund"

# Gründe, bei denen die Arbeit weiterläuft und nur der Kontext wechselt.
WEICHE_GRUENDE = {"clear", "compact", "resume"}


def abloesen(roh: str) -> bool:
    """
    Startet dieses Skript erneut, abgelöst von Claude Code.

    Die Nutzlast geht über die Standardeingabe mit. Der Kindprozess
    bekommt eine eigene Sitzung (POSIX) bzw. eine eigene Prozessgruppe
    ohne Konsole (Windows), damit ihn das Beenden von Claude Code nicht
    mitreißt.
    """
    optionen = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        optionen["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        optionen["start_new_session"] = True

    try:
        prozess = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), VORDERGRUND], **optionen
        )
        prozess.stdin.write(roh.encode("utf-8"))
        prozess.stdin.close()
        return True
    except Exception:
        return False


def abschluss(hook_input):
    """Die eigentliche Arbeit: letzter Status, dann alles freigeben."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from lib import reservierung
    from lib.autostatus import schreibe_status
    from lib.host import CLAUDE, LABELS
    from lib.channel import (
        channel_is_ready,
        get_agent_name,
        get_channel_dir,
        get_current_branch,
        get_project_dir,
        touch_throttle,
    )

    # Claude Code nennt das Feld 'reason'. Bis 0.4 wurde hier
    # 'session_end_reason' gelesen, das es nie gab, und jedes Ende galt
    # als Sessionende, auch ein /clear.
    grund = (hook_input.get("reason") or hook_input.get("session_end_reason") or "").lower()
    anlass = "Sessionende" if grund not in WEICHE_GRUENDE else f"Sessionwechsel ({grund})"

    geschrieben = schreibe_status(
        hook_input.get("transcript_path", ""),
        quelle="sessionende",
        anlass=anlass,
        werkzeug=LABELS[CLAUDE],
    )

    project_dir = get_project_dir()
    if geschrieben:
        touch_throttle(project_dir)

    # Reservierungen aufheben. Ohne das hält eine beendete Session ihre
    # Dateien bis zum Ablauf besetzt.
    channel_dir = get_channel_dir(project_dir)
    if channel_is_ready(channel_dir):
        reservierung.freigeben(
            channel_dir,
            get_agent_name(project_dir),
            get_current_branch(project_dir),
            hook_input.get("session_id", ""),
            None,
        )


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        roh = sys.stdin.read()
    except Exception:
        roh = ""

    if VORDERGRUND not in sys.argv[1:]:
        if abloesen(roh):
            return
        # Ablösen ging nicht. Dann wenigstens versuchen, was in der
        # knappen Zeit geht.

    try:
        hook_input = json.loads(roh) if roh.strip() else {}
        if not isinstance(hook_input, dict):
            hook_input = {}
    except Exception:
        hook_input = {}

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib.channel import setup_stdio

        setup_stdio()
        abschluss(hook_input)
    except Exception as exc:
        print(f"team-sync: Abschlussstatus fehlgeschlagen: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
