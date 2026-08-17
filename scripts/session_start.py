#!/usr/bin/env python3
"""
SessionStart-Hook: liest den Team-Channel und gibt ihn als Kontext in
die neue Session.

Was ankommt: offene Fragen an einen selbst, woran die anderen zuletzt
gearbeitet haben, und die zuletzt getroffenen Entscheidungen. Genau
das, was sonst zu Beginn jeder Session mühsam neu erklärt werden
müsste.

Der Hook schreibt nichts und ändert nichts. Wenn irgendetwas nicht
klappt, gibt er einfach keinen Kontext aus und die Session startet
normal.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import empfang
from lib.channel import (
    cache_verwerfen,
    channel_is_ready,
    get_agent_name,
    get_channel_dir,
    get_project_dir,
    pull_channel,
    setup_stdio,
)
from lib.render import build_context

# Bewusst knapp: ein Sessionstart darf nicht spürbar hängen, nur weil
# das Netz gerade langsam ist. Ohne frischen Pull wird der zuletzt
# lokal bekannte Stand gelesen, der ist fast immer gut genug.
PULL_TIMEOUT = 8


def main():
    setup_stdio()

    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        project_dir = get_project_dir()
        # Beim Sessionstart neu ermitteln: Wurde der Channel seit dem
        # letzten Mal eingerichtet, zeigt ein alter Cache noch auf einen
        # Ort, an dem nichts lag.
        cache_verwerfen(project_dir)
        channel_dir = get_channel_dir(project_dir)

        if not channel_is_ready(channel_dir):
            # Kein Setup: still bleiben. Eine Warnung bei jedem
            # Sessionstart in jedem Projekt ohne Channel wäre nur lästig.
            return

        pull_channel(channel_dir, timeout=PULL_TIMEOUT)
        me = get_agent_name(project_dir)
        kontext = build_context(channel_dir, me)

        # Der Rückkanal soll später nur Neues melden. Alles, was gerade
        # im Startkontext steht, gilt deshalb ab jetzt als gesehen —
        # sonst wiederholt die erste Meldung, was oben schon steht.
        empfang.erstlauf_stumm_schalten(channel_dir, project_dir, me)
    except Exception as exc:
        print(f"team-sync: Kontext konnte nicht gelesen werden: {exc}", file=sys.stderr)
        return

    if not kontext:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": kontext,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
