#!/usr/bin/env python3
"""
Einstiegspunkt für die Antigravity-Hooks.

Antigravity kennt andere Ereignisse als Claude Code. Statt jedes davon
in ein eigenes Skript zu legen, gibt es hier eines mit dem Ereignis als
Argument. Aufgerufen wird es aus der hooks.json, die
scripts/setup_antigravity.py schreibt:

    python3 /pfad/zu/team-sync/scripts/antigravity_hook.py pre-invocation
    python3 /pfad/zu/team-sync/scripts/antigravity_hook.py post-invocation
    python3 /pfad/zu/team-sync/scripts/antigravity_hook.py stop

Die Zuordnung zu den Claude-Code-Ereignissen:

    PreInvocation    erster Aufruf einer Unterhaltung entspricht
                     SessionStart, jeder weitere liefert den Rückkanal
    PostInvocation   entspricht Stop, also dem gedrosselten
                     Zwischenstand nach einer Antwort
    Stop             entspricht SessionEnd, letzter Stand und Freigabe
                     aller Reservierungen

PreInvocation trägt zwei Aufgaben, weil es der einzige Zeitpunkt ist,
an dem sich unter Antigravity Text in den Kontext geben lässt. Ob es
sich um den ersten Aufruf handelt, steht in einer Merkdatei im
Git-Verzeichnis, denn ein eigenes Startereignis gibt es nicht.

Wie überall im Plugin gilt: Ein Fehler hier darf die Sitzung nicht
aufhalten. Im Zweifel wird nichts gemeldet und nichts geschrieben.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import empfang, host, reservierung
from lib.autostatus import schreibe_status
from lib.channel import (
    channel_is_ready,
    cache_verwerfen,
    get_agent_name,
    get_channel_dir,
    get_current_branch,
    get_git_dir,
    get_project_dir,
    pull_channel,
    setup_stdio,
    should_checkpoint,
    touch_throttle,
)
from lib.render import build_context

MIN_INTERVAL_SECONDS = int(os.environ.get("TEAM_SYNC_CHECKPOINT_SECONDS", "600"))

# Knapp gehalten, aus demselben Grund wie beim Sessionstart unter
# Claude Code: Ein hängender Netzwerkaufruf darf den ersten Zug einer
# Unterhaltung nicht spürbar verzögern.
PULL_TIMEOUT = 8

# Wie lange eine begonnene Unterhaltung als bekannt gilt (Sekunden).
# Danach zählt der nächste Aufruf wieder als Start. Das räumt die
# Merkdatei auf und schadet nichts: Wer nach zwölf Stunden weiterarbeitet,
# kann den Teamstand ohnehin gut noch einmal gebrauchen.
STARTMERKER_GUELTIG = int(os.environ.get("TEAM_SYNC_AG_START_SECONDS", "43200"))


# ---------------------------------------------------------------------------
# Merkdatei für begonnene Unterhaltungen
# ---------------------------------------------------------------------------


def _merker_pfad(project_dir: Path):
    git_dir = get_git_dir(project_dir)
    return (git_dir / "team-sync-antigravity.json") if git_dir else None


def ist_erster_aufruf(project_dir: Path, unterhaltung: str) -> bool:
    """
    Ist das der erste PreInvocation dieser Unterhaltung?

    Ohne Kennung wird jeder Aufruf als Start gewertet. Das ist die
    sichere Richtung: Lieber einmal zu viel den Teamstand einlesen als
    eine ganze Sitzung ohne ihn laufen lassen.
    """
    if not unterhaltung:
        return True

    pfad = _merker_pfad(project_dir)
    if pfad is None:
        return True

    jetzt = time.time()
    try:
        bekannt = json.loads(pfad.read_text(encoding="utf-8")).get("gesehen", {})
        if not isinstance(bekannt, dict):
            bekannt = {}
    except Exception:
        bekannt = {}

    frisch = {
        kennung: zeit
        for kennung, zeit in bekannt.items()
        if isinstance(zeit, (int, float)) and (jetzt - zeit) < STARTMERKER_GUELTIG
    }
    erster = unterhaltung not in frisch
    frisch[unterhaltung] = jetzt

    try:
        # Nur die jüngsten behalten, sonst wächst die Datei über Monate.
        juengste = sorted(frisch.items(), key=lambda paar: paar[1])[-50:]
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(json.dumps({"gesehen": dict(juengste)}), encoding="utf-8")
    except Exception:
        pass

    return erster


# ---------------------------------------------------------------------------
# Ereignisse
# ---------------------------------------------------------------------------


def pre_invocation(daten) -> str:
    """
    Vor dem Modellaufruf: Teamstand beim ersten Mal, danach das Neue.

    Zusätzlich wird hier das Postfach geleert. Der Hinweis auf eine
    belegte Datei kann unter Antigravity nicht direkt aus dem
    PreToolUse-Hook kommen, siehe lib/host.py, deshalb wartet er hier
    auf seine Gelegenheit.
    """
    project_dir = get_project_dir()
    teile = []

    zurueckgestellt = host.postfach_abholen(project_dir)
    if zurueckgestellt:
        teile.append(zurueckgestellt)

    erster = ist_erster_aufruf(project_dir, daten.session)
    if erster:
        # Wurde der Channel seit dem letzten Mal eingerichtet, zeigt ein
        # alter Cache noch auf einen Ort, an dem nichts lag.
        cache_verwerfen(project_dir)

    channel_dir = get_channel_dir(project_dir)
    if not channel_is_ready(channel_dir):
        # Kein Setup: still bleiben. Eine Warnung bei jedem Modellaufruf
        # in jedem Projekt ohne Channel wäre nur lästig.
        return "\n\n".join(teile)

    me = get_agent_name(project_dir)

    if erster:
        pull_channel(channel_dir, timeout=PULL_TIMEOUT)
        kontext = build_context(channel_dir, me)
        if kontext:
            teile.append(kontext)
        # Alles, was gerade im Startkontext steht, gilt ab jetzt als
        # gesehen, sonst wiederholt die erste Meldung des Rückkanals,
        # was oben schon steht.
        empfang.erstlauf_stumm_schalten(channel_dir, project_dir, me)
        return "\n\n".join(teile)

    if empfang.faellig(project_dir):
        pull_channel(channel_dir, timeout=15)
        neues = empfang.neuigkeiten(channel_dir, project_dir, me)
        if neues:
            teile.append(neues)

    return "\n\n".join(teile)


def post_invocation(daten):
    """Nach der Antwort: gedrosselt einen Zwischenstand schreiben."""
    project_dir = get_project_dir()

    erzwungen = os.environ.get("TEAM_SYNC_FORCE") == "1"
    if not (erzwungen or should_checkpoint(project_dir, MIN_INTERVAL_SECONDS)):
        return

    geschrieben = schreibe_status(
        daten.transcript,
        quelle="zwischenstand",
        anlass="automatisch",
        werkzeug=daten.label,
    )
    if geschrieben:
        touch_throttle(project_dir)


def stop(daten):
    """Beim Ende: letzter Stand und alle Reservierungen freigeben."""
    project_dir = get_project_dir()

    geschrieben = schreibe_status(
        daten.transcript,
        quelle="sessionende",
        anlass="Sessionende",
        werkzeug=daten.label,
    )
    if geschrieben:
        touch_throttle(project_dir)

    channel_dir = get_channel_dir(project_dir)
    if channel_is_ready(channel_dir):
        reservierung.freigeben(
            channel_dir,
            get_agent_name(project_dir),
            get_current_branch(project_dir),
            daten.session,
            None,
        )


EREIGNISSE = {
    "pre-invocation": "PreInvocation",
    "post-invocation": "PostInvocation",
    "stop": "Stop",
}


def main():
    setup_stdio()

    # Dieses Skript wird ausschließlich aus der Antigravity-hooks.json
    # aufgerufen. Die Erkennung anhand der Nutzlast bliebe trotzdem
    # richtig, aber bei leerer Eingabe fiele sie auf Claude Code zurück
    # und das Antwortformat wäre falsch. Ein Vorgabewert ist hier
    # verlässlicher als eine Vermutung.
    os.environ.setdefault("TEAM_SYNC_HOST", host.ANTIGRAVITY)

    name = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    if name not in EREIGNISSE:
        print(
            f"Unbekanntes Ereignis: {name or '(keines)'}\n"
            f"Erwartet: {', '.join(sorted(EREIGNISSE))}",
            file=sys.stderr,
        )
        return 1

    daten = host.lies_ereignis(EREIGNISSE[name])
    text = ""

    try:
        if name == "pre-invocation":
            text = pre_invocation(daten)
        elif name == "post-invocation":
            post_invocation(daten)
        else:
            stop(daten)
    except Exception as exc:
        # Nur auf die Standardfehlerausgabe. Die Standardausgabe gehört
        # dem Protokoll, und ein Fehlertext darin würde als ungültige
        # Antwort gelesen.
        print(f"team-sync: {name} fehlgeschlagen: {exc}", file=sys.stderr)

    if text:
        host.melde_kontext(daten.host, EREIGNISSE[name], text)
    else:
        host.fertig(daten.host)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
