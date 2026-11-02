#!/usr/bin/env python3
"""
PreToolUse-Hook: warnt vor einer Datei, an der gerade jemand anders
sitzt.

Blockiert nie dauerhaft. Sitzt jemand auf demselben Branch an der
Datei, wird nur der erste Edit einmal angehalten, mit Begründung und
dem fertigen Befehl für eine Anfrage. Der nächste Versuch geht durch.
Bis 0.5 gab es nur einen Begleittext, und der kommt bei Claude erst mit
dem Ergebnis des Werkzeugs an, also nach dem Edit. Gegen doppelte
Arbeit half er damit nicht. Ein Hook, der immer wieder verweigert,
brächte dagegen eine autonome Session unbemerkt zum Stehen, deshalb
genau einmal und nie öfter.

In die Rechte greift der Hook nicht ein. Er gibt nie "allow" zurück,
denn das würde die Rückfrage überspringen, ob Claude die Datei
überhaupt bearbeiten darf.

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

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Auf "aus" gesetzt, wird nie angehalten, nur hingewiesen.
ANHALTEN = (os.environ.get("TEAM_SYNC_ANHALTEN") or "").strip().lower() not in (
    "0", "aus", "off", "nein", "no", "false",
)

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
        "Die Antwort kommt als Meldung. Komm dann auf diese Datei zurück."
    )
    if not autonom:
        anweisung += " Oder frag den Nutzer, ob ihr euch kurz abstimmt."

    kopf = (
        f"team-sync: **`{datei}` ist belegt.** "
        f"{reservierung.beschreibe(eintrag)}, derselbe Branch wie deiner.\n\n"
    )

    if ANHALTEN and not anfrage.angehalten_kuerzlich(project_dir, datei):
        if anfrage.merke_angehalten(project_dir, datei):
            host.halte_an(
                daten.host,
                kopf
                + "Dieser Edit wurde deshalb einmal angehalten, die Datei ist "
                "unverändert. Betrifft dein Vorhaben denselben Abschnitt, "
                f"entsteht hier doppelte Arbeit. {anweisung}\n\n"
                "Betrifft es einen anderen Abschnitt oder musst du jetzt sofort "
                "an die Datei, wiederhole den Edit einfach. Er geht dann durch.",
                project_dir,
            )
            return

    melde(
        kopf
        + f"Betrifft dein Vorhaben denselben Abschnitt, entsteht hier doppelte "
        f"Arbeit. {anweisung}"
    )


def _cli_aufruf(host_name: str) -> str:
    """
    Der Aufruf der Kommandozeile, mit echtem Pfad.

    Bis 0.4 stand hier für Claude Code ${CLAUDE_PLUGIN_ROOT}. Diese
    Variable ersetzt Claude Code aber nur in Hooks und Commands, nicht im
    Text, den ein Hook zurückgibt, und in der Shell von Claude ist sie
    nicht gesetzt. Der Befehl wurde dort zu python3 "/scripts/team_sync.py"
    und schlug fehl. Damit lief keine einzige Dateianfrage je durch. Der
    Hook kennt den echten Pfad, also nennt er ihn, unter beiden
    Programmen gleich.
    """
    from lib.channel import cli_befehl

    return cli_befehl()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ein Fehler hier darf niemals einen Edit verhindern.
        pass
