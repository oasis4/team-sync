---
trigger: always_on
description: Geteilter Arbeitsstand des Teams über den Branch team-channel
---

# Team-Channel

An diesem Repository arbeiten mehrere Personen parallel, jede in einer
eigenen Agentensitzung. Manche benutzen Antigravity, manche Claude Code.
Damit alle voneinander wissen, liegt der geteilte Stand als Markdown im
selben Repository, auf dem Branch `team-channel`, ausgecheckt als
zweiter Arbeitsordner neben dem Projekt.

Gepflegt wird das vom Plugin team-sync. Das meiste passiert ohne dein
Zutun über Hooks: Beim ersten Zug einer Unterhaltung bekommst du den
Stand der anderen, während der Arbeit werden angefasste Dateien
reserviert, alle paar Minuten wird geschrieben und gelesen.

## Was du selbst tun sollst

**Reagiere auf Meldungen aus dem Channel.** Sie kommen als
Systemnachricht und stammen aus einer anderen, parallel laufenden
Sitzung am selben Repository. Eine neue Festlegung des Teams gilt auch
mitten in deiner Aufgabe. Eine offene Frage an den Nutzer sprichst du
an, statt sie zu übergehen.

**Ist eine Datei belegt, warte nicht.** Der Hinweis nennt die Person und
seit wann. Leg eine Anfrage ab, arbeite an einem anderen Punkt weiter
und komm später zurück. Warten kostet genau die Zeit, die das Werkzeug
sparen soll.

**Schreib in den Channel über die Kommandozeile, nie von Hand.**
Dateinamen, Kopffelder, Commit und Push erledigt das Skript. Der Ordner
`team-channel` wird nicht direkt bearbeitet und nie nach `main` gemergt.

## Die Aufrufe

    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" uebersicht
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" fragen
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" ask --to <person> --titel "..." --text "..."
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" answer --id <id> --text "..."
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" decide --titel "..." --entscheidung "..." --begruendung "..."
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" sync --text "..."
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" anfrage --datei <pfad> --text "..."
    python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" doctor

Enthält ein Text Anführungszeichen oder Zeilenumbrüche, schreib ihn in
eine temporäre Datei und übergib `--text-file <pfad>`. Das ist
zuverlässiger als jedes Quoting.

Meldet ein Aufruf, dass der Push nicht geklappt hat, sag das
ausdrücklich weiter. Der Eintrag liegt dann nur lokal und niemand im
Team sieht ihn.
