#!/usr/bin/env python3
"""
PreToolUse-Hook: warnt vor einer Datei, an der gerade jemand anders
sitzt.

Blockiert nie. Die Entscheidung bleibt bei Claude, der Hook liefert nur
die Information und eine klare Handlungsanweisung. Ein Hook, der zu oft
verweigert, bringt eine Auto-Session stundenlang unbemerkt zum Stehen —
das wäre schlimmer als die doppelte Arbeit, die er verhindern soll.

Dieses Skript läuft vor JEDEM Edit. Deshalb gilt hier eine Regel, die
sonst nirgends im Plugin gilt:

    Kein Netzwerkzugriff, kein git-Aufruf, so früh aussteigen wie
    möglich.

Der aktuelle Stand kommt aus dem, was der Stop-Hook zuletzt gepullt hat.
Die Warnung ist dadurch ein paar Minuten alt. Für den realen Fall — "A
sitzt seit zwanzig Minuten an der Datei" — genügt das vollkommen.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RELEVANTE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Modi, in denen niemand mitliest und Claude allein entscheidet.
AUTONOME_MODI = {"auto", "bypassPermissions", "dontAsk", "acceptEdits"}


def melde(text: str):
    """Gibt Claude einen Hinweis, ohne den Aufruf aufzuhalten."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


def main():
    try:
        roh = sys.stdin.read()
        payload = json.loads(roh) if roh else {}
    except Exception:
        return

    if payload.get("tool_name") not in RELEVANTE_TOOLS:
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    ziel = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not ziel:
        return

    # Ab hier erst die Bibliothek laden. Bei einem Aufruf, der uns nicht
    # betrifft, sparen wir uns die Importe komplett.
    from lib.channel import get_project_dir, schneller_kontext, setup_stdio
    from lib import anfrage, reservierung

    setup_stdio()

    project_dir = get_project_dir()
    kontext = schneller_kontext(project_dir)
    if not kontext:
        return

    channel_dir = Path(kontext.get("channel", ""))
    try:
        if not (channel_dir / reservierung.ORDNER).is_dir():
            return
    except Exception:
        return

    ich = kontext.get("person", "")
    mein_branch = kontext.get("branch", "")
    datei = reservierung.normalisiere(ziel, project_dir)

    belegt = reservierung.belegt_von(channel_dir, ich, datei)
    if not belegt:
        return

    eintrag = belegt[0]
    gleicher_branch = bool(mein_branch) and eintrag.get("branch") == mein_branch
    autonom = payload.get("permission_mode") in AUTONOME_MODI
    session = payload.get("session_id", "")

    # Läuft bereits eine Klärung?
    offen = anfrage.offen_und_wartend(channel_dir, datei)
    if offen:
        melde(
            f"team-sync: `{datei}` ist von {reservierung.beschreibe(eintrag)} "
            f"reserviert. Eine Anfrage dazu läuft bereits und ist noch "
            f"unbeantwortet. Arbeite an etwas anderem weiter und komm später "
            f"zurück, statt hier erneut zu fragen."
        )
        return

    geklaert = anfrage.beantwortet_kuerzlich(channel_dir, datei)
    if geklaert:
        melde(
            f"team-sync: `{datei}` ist von {reservierung.beschreibe(eintrag)} "
            f"reserviert, die Rückfrage dazu wurde aber schon beantwortet:\n\n"
            f"> {anfrage.nur_antwort(geklaert['body'])[:400]}\n\n"
            f"Halte dich an diese Antwort."
        )
        return

    if anfrage.schon_gefragt(project_dir, datei):
        melde(
            f"team-sync: `{datei}` ist von {reservierung.beschreibe(eintrag)} "
            f"reserviert. Du hast vor Kurzem bereits danach gefragt und "
            f"keine Antwort bekommen — die andere Session ist womöglich längst "
            f"beendet. Mach weiter, aber sei bei größeren Umbauten vorsichtig."
        )
        return

    if not gleicher_branch:
        # Verschiedene Branches heißt meistens: git löst das später. Ein
        # knapper Hinweis genügt, sonst wird aus der Warnung ein
        # Fehlalarm, den beim dritten Mal niemand mehr liest.
        melde(
            f"team-sync: An `{datei}` arbeitet gerade auch "
            f"{reservierung.beschreibe(eintrag)} — anderer Branch als deiner "
            f"(`{mein_branch}`), also vermutlich unkritisch. Nur falls ihr "
            f"dasselbe zweimal baut, wäre das der Moment, es zu merken."
        )
        return

    anweisung = (
        "Lege jetzt eine Anfrage ab und arbeite währenddessen an einem "
        "anderen Punkt weiter — nicht warten, das kostet nur Zeit:\n\n"
        f'    python3 "${{CLAUDE_PLUGIN_ROOT}}/scripts/team_sync.py" anfrage '
        f'--datei "{datei}" --text "<was du vorhast>"\n\n'
        "Komm später auf diese Datei zurück."
    )
    if not autonom:
        anweisung += " Oder frag den Nutzer, ob ihr euch kurz abstimmt."

    melde(
        f"team-sync: **`{datei}` ist belegt.** "
        f"{reservierung.beschreibe(eintrag)} — derselbe Branch wie deiner.\n\n"
        f"Betrifft dein Vorhaben denselben Abschnitt, entsteht hier doppelte "
        f"Arbeit. {anweisung}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ein Fehler hier darf niemals einen Edit verhindern.
        pass
