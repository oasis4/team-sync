#!/usr/bin/env python3
"""
SessionEnd-Hook: schreibt den abschließenden Status.

Feuert beim echten Beenden einer Session, also bei /clear, /exit oder
Logout. Anders als der Zwischenstand ist das hier nicht gedrosselt, ein
Sessionende ist immer eine Aktualisierung wert.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.autostatus import schreibe_status
from lib.channel import get_project_dir, setup_stdio, touch_throttle

# Gründe, bei denen die Arbeit weiterläuft und nur der Kontext wechselt.
WEICHE_GRUENDE = {"clear", "compact", "resume"}


def read_hook_input():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def main():
    setup_stdio()
    hook_input = read_hook_input()

    try:
        grund = (hook_input.get("session_end_reason") or "").lower()
        anlass = "Sessionende" if grund not in WEICHE_GRUENDE else f"Sessionwechsel ({grund})"

        geschrieben = schreibe_status(
            hook_input.get("transcript_path", ""),
            quelle="sessionende",
            anlass=anlass,
        )
        if geschrieben:
            touch_throttle(get_project_dir())
    except Exception as exc:
        print(f"team-sync: Abschlussstatus fehlgeschlagen: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
