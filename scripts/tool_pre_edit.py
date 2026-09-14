#!/usr/bin/env python3
"""
PreToolUse-Hook: warnt vor einer Datei, an der gerade jemand anders
sitzt.

Blockiert nie. Die Entscheidung bleibt beim Agenten, der Hook liefert
nur die Information und eine klare Handlungsanweisung. Ein Hook, der zu
oft verweigert, bringt eine Auto-Session stundenlang unbemerkt zum
Stehen, und das wäre schlimmer als die doppelte Arbeit, die er
verhindern soll.

Dieses Skript läuft vor JEDEM Edit. Deshalb gilt hier eine Regel, die
sonst nirgends im Plugin gilt:

    Kein Netzwerkzugriff, kein git-Aufruf, so früh aussteigen wie
    möglich.

Der aktuelle Stand kommt aus dem, was der letzte Zwischenstand gepullt
hat. Die Warnung ist dadurch ein paar Minuten alt. Für den realen Fall,
"A sitzt seit zwanzig Minuten an der Datei", genügt das vollkommen.

Läuft unter Claude Code und unter Antigravity. Der Unterschied steckt
in lib/host.py, hier ist nur noch die Sachlogik.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Modi, in denen niemand mitliest und der Agent allein entscheidet.
AUTONOME_MODI = {"auto", "bypassPermissions", "dontAsk", "acceptEdits"}


def main():
    from lib import host

    daten = host.lies_ereignis("PreToolUse")

    if not daten.ist_edit():
        host.erlaube(daten.host)
        return

    # Ab hier erst den Rest laden. Bei einem Aufruf, der uns nicht
    # betrifft, sparen wir uns die Importe komplett.
    from lib.channel import get_project_dir, schneller_kontext, setup_stdio
    from lib import anfrage, reservierung

    setup_stdio()

    project_dir = get_project_dir()
    kontext = schneller_kontext(project_dir)
    if not kontext:
        host.erlaube(daten.host)
        return

    channel_dir = Path(kontext.get("channel", ""))
    try:
        if not (channel_dir / reservierung.ORDNER).is_dir():
            host.erlaube(daten.host)
            return
    except Exception:
        host.erlaube(daten.host)
        return

    ich = kontext.get("person", "")
    mein_branch = kontext.get("branch", "")
    datei = reservierung.normalisiere(daten.datei, project_dir)

    belegt = reservierung.belegt_von(channel_dir, ich, datei)
    if not belegt:
        host.erlaube(daten.host)
        return

    eintrag = belegt[0]
    gleicher_branch = bool(mein_branch) and eintrag.get("branch") == mein_branch
    autonom = daten.modus in AUTONOME_MODI

    def melde(text):
        host.melde_werkzeug_hinweis(daten.host, text, project_dir)

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
            f"keine Antwort bekommen, die andere Session ist womöglich längst "
            f"beendet. Mach weiter, aber sei bei größeren Umbauten vorsichtig."
        )
        return

    if not gleicher_branch:
        # Verschiedene Branches heißt meistens: git löst das später. Ein
        # knapper Hinweis genügt, sonst wird aus der Warnung ein
        # Fehlalarm, den beim dritten Mal niemand mehr liest.
        melde(
            f"team-sync: An `{datei}` arbeitet gerade auch "
            f"{reservierung.beschreibe(eintrag)}, anderer Branch als deiner "
            f"(`{mein_branch}`), also vermutlich unkritisch. Nur falls ihr "
            f"dasselbe zweimal baut, wäre das der Moment, es zu merken."
        )
        return

    anweisung = (
        "Lege jetzt eine Anfrage ab und arbeite währenddessen an einem "
        "anderen Punkt weiter, nicht warten, das kostet nur Zeit:\n\n"
        f'    {_cli_aufruf(daten.host)} anfrage '
        f'--datei "{datei}" --text "<was du vorhast>"\n\n'
        "Komm später auf diese Datei zurück."
    )
    if not autonom:
        anweisung += " Oder frag den Nutzer, ob ihr euch kurz abstimmt."

    melde(
        f"team-sync: **`{datei}` ist belegt.** "
        f"{reservierung.beschreibe(eintrag)}, derselbe Branch wie deiner.\n\n"
        f"Betrifft dein Vorhaben denselben Abschnitt, entsteht hier doppelte "
        f"Arbeit. {anweisung}"
    )


def _cli_aufruf(host_name: str) -> str:
    """
    Der Aufruf der Kommandozeile, so wie ihn dieser Host versteht.

    Claude Code ersetzt CLAUDE_PLUGIN_ROOT, Antigravity ersetzt keine
    Platzhalter. Dort steht deshalb der echte Pfad, den dieses Skript
    ohnehin kennt, weil es selbst darin liegt.
    """
    from lib.host import ANTIGRAVITY

    if host_name == ANTIGRAVITY:
        return f'python3 "{Path(__file__).resolve().parent / "team_sync.py"}"'
    return 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py"'


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ein Fehler hier darf niemals einen Edit verhindern.
        pass
