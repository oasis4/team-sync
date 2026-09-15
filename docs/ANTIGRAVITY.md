# team-sync mit Google Antigravity

team-sync ist als Claude-Code-Plugin entstanden. Der geteilte Stand
liegt aber nur als Markdown auf einem Git-Branch, und dem ist gleich,
welches Programm ihn beschreibt. Wer mit Antigravity arbeitet, kann
deshalb im selben Team mitarbeiten wie alle anderen.

Der Fall, für den das gebaut ist: Person A nutzt Antigravity, Person B
und C nutzen Claude Code, alle drei am selben Repository. Alle sehen
dieselben Reservierungen, Fragen und Entscheidungen.

---

## Einrichten

Zwei Schritte, beide einmal pro Person und Projekt.

**1. Den Channel anlegen**, genau wie alle anderen auch:

```bash
git clone https://github.com/oasis4/team-sync.git ~/werkzeuge/team-sync
cd /pfad/zu/deinem/projekt
python3 ~/werkzeuge/team-sync/scripts/setup_channel.py
```

**2. Antigravity eintragen:**

```bash
python3 ~/werkzeuge/team-sync/scripts/setup_antigravity.py
```

Danach Antigravity einmal neu starten.

Geschrieben wird in den Projektordner:

```
.agents/
├── hooks.json          Gruppe "team-sync", verweist auf den Klon oben
├── rules/team-sync.md  Dauerregel, erklärt dem Agenten den Channel
└── workflows/          team, ask, answer, decide, sync
```

In diesen Dateien stehen absolute Pfade zu deinem Klon. Sie gehören
deshalb nicht ins Repository, sonst zeigen sie auf dem Rechner der
nächsten Person ins Leere und ihre Hooks tun still nichts. Einmal
eintragen:

```bash
echo ".agents/" >> .gitignore
```

Das Skript erinnert daran, wenn der Eintrag fehlt.

Prüfen:

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py doctor
```

Der Bericht endet mit einem Abschnitt zu Antigravity. Zeigt ein Hook auf
eine Datei, die es nicht gibt, steht das dort als Problem. Genau das
passiert, wenn der Klon später verschoben wird, denn in der hooks.json
stehen absolute Pfade.

### Optionen

| Option | Wirkung |
|---|---|
| `--global` | Schreibt nach `~/.gemini/config/` statt in den Projektordner. Gilt dann für alle Projekte. |
| `--dir <pfad>` | Anderer Ort für den `.agents`-Ordner |
| `--python <befehl>` | Anderer Python-Aufruf in den Hooks, etwa `py -3` unter Windows |
| `--dry-run` | Zeigt nur, was passieren würde |
| `--entfernen` | Nimmt alles wieder heraus |

Liegt die rechnerweite Konfiguration bei dir nicht unter
`~/.gemini/config`, sag es über `TEAM_SYNC_GEMINI_DIR`. Sowohl
`--global` als auch `doctor` richten sich danach.

`--global` ist bequem und trotzdem nicht die Vorgabe. Die Hooks laufen
dann auch in Repositories ohne Channel. Schaden tun sie dort nicht, sie
steigen sofort wieder aus, aber jeder Modellaufruf kostet einen
Prozessstart mehr.

Eine bestehende `hooks.json` wird nicht überschrieben. Das Skript liest
sie ein, legt eine Sicherungskopie an und ergänzt nur die Gruppe
`team-sync`. Ist die Datei kein lesbares JSON, bricht es ab und ändert
nichts.

---

## Wie die Ereignisse zugeordnet sind

Antigravity kennt andere Ereignisse als Claude Code. Die Sachlogik ist
in beiden Fällen dieselbe, nur der Aufhänger unterscheidet sich.

| Claude Code | Antigravity | Was passiert |
|---|---|---|
| `SessionStart` | `PreInvocation`, erster Aufruf | Teamstand in den Kontext |
| `Stop` | `PostInvocation` | Gedrosselter Zwischenstand |
| `SessionEnd` | `Stop` | Letzter Stand, Reservierungen frei |
| `PreToolUse` | `PreToolUse` | Hinweis auf eine belegte Datei |
| `PostToolUse` | `PostToolUse` | Datei beim ersten Zugriff reservieren |

Ein eigenes Startereignis gibt es unter Antigravity nicht. Ob ein
`PreInvocation` der erste einer Unterhaltung ist, merkt sich das Plugin
im Git-Verzeichnis des Projekts. Jeder weitere Aufruf liefert stattdessen
den Rückkanal, also das, was seit dem letzten Blick dazugekommen ist.

Alles Programmspezifische steckt in `scripts/lib/host.py`. Der Rest des
Plugins sieht nur ein normalisiertes Ereignis und weiß nicht, woher es
kommt.

---

## Zwei Unterschiede, die im Alltag auffallen

Beides folgt aus dem, was Antigravity zulässt, nicht aus einer
Designentscheidung. Wer es weiß, ordnet es richtig ein.

### Der Hinweis auf eine belegte Datei kommt einen Schritt später

Unter Claude Code darf ein `PreToolUse`-Hook den Aufruf erlauben und
gleichzeitig einen Text mitgeben. Unter Antigravity erwartet das
Protokoll an dieser Stelle genau eine Erlaubnis und sonst nichts. Ein
zusätzliches Feld kann der Parser ablehnen, und eine abgelehnte
Hook-Antwort hat in anderen Projekten schon dazu geführt, dass jeder
Werkzeugaufruf verweigert wurde.

Deshalb wird der Hinweis abgelegt und beim nächsten Modellaufruf
nachgereicht. Praktisch heißt das: Der Agent schreibt einmal in die
Datei und erfährt danach, dass jemand anders daran sitzt. Das ist
schlechter als sofort und deutlich besser als eine Sitzung, die stehen
bleibt.

Der Hinweis verfällt nach einer Viertelstunde, siehe
`TEAM_SYNC_POSTFACH_SECONDS`. Ein Hinweis auf eine Belegung, der so alt
ist, beschreibt die Lage meistens nicht mehr.

### Der automatische Status ist gröber

Der Status besteht aus zwei Teilen: woran gearbeitet wird und welche
Dateien angefasst wurden.

Die **Dateiliste** ist unter beiden Programmen gleich verlässlich. Sie
entsteht aus den eigenen Hooks, nicht aus dem Transkript.

Der **Text** kommt aus dem Transkript, und dessen Format gehört dem
Hostprogramm. Für Claude Code ist es dokumentiert und stabil, für
Antigravity nicht. Das Plugin liest deshalb zuerst das bekannte Format
und fällt sonst auf eine nachgiebige Suche zurück, die keine feste
Struktur voraussetzt. Findet auch die nichts, steht dort
`_nicht ermittelbar_` und der Rest des Status stimmt trotzdem.

Wem das zu dünn ist, der nimmt `/sync`. Dort formuliert der Agent die
Zusammenfassung aus dem laufenden Kontext, und das ist ohnehin die
bessere Fassung.

---

## Wenn die Reservierungen ausbleiben

Der wahrscheinlichste Grund: Das Plugin erkennt die schreibenden
Werkzeuge nicht.

Unter Claude Code heißen sie `Edit`, `Write`, `MultiEdit` und
`NotebookEdit`, und das ändert sich nicht. Unter Antigravity hängen die
Namen von Version und Modell ab. Das Plugin prüft deshalb zweierlei:
Steckt überhaupt ein Dateipfad im Aufruf, und klingt der Name schreibend
(`write`, `edit`, `create`, `replace`, `patch`, `apply` und einige
mehr). Ein Lesezugriff löst damit keine Reservierung aus.

Heißt das Werkzeug in deiner Installation anders, trag die Namen fest
ein:

```bash
export TEAM_SYNC_AG_EDIT_TOOLS="apply_diff,create_file"
```

Welchen Namen dein Werkzeug hat, steht in der Werkzeugliste von
Antigravity oder im Transkript der Sitzung.

---

## Was auf beiden Seiten gleich ist

- **Der Name im Channel.** Beide lesen `git config user.name`, oder
  `TEAM_AGENT_NAME`, wenn gesetzt. Wer denselben Namen benutzt, ist
  dieselbe Person, gleich mit welchem Programm.
- **Die Dateipfade.** Alles wird projektrelativ und mit Schrägstrichen
  abgelegt. Sonst wäre `C:/Users/lars/projekt/auth.py` etwas anderes als
  `/home/max/projekt/auth.py`, und keine Kollision fiele je auf.
- **Die Zeilenenden.** Immer Unix, sonst zeigt jeder Wechsel zwischen
  Windows und Linux die ganze Datei als geändert.
- **Das Dateiformat.** Dieselben Kopffelder, derselbe Aufbau. Ein Status
  aus Antigravity ist für Claude Code ein ganz normaler Status.

Im Status steht zusätzlich ein Feld `werkzeug`. Es taucht in der
Übersicht auf, damit sichtbar ist, wer womit arbeitet. Das ist keine
Statistik, sondern eine Lesehilfe: Eine Reservierung aus Antigravity
kann etwas träger sein, und das soll niemand für einen Fehler halten.

---

## Grenzen, offen gesagt

Das Hook-Protokoll von Antigravity ist weniger festgeschrieben als das
von Claude Code und hat sich seit seiner ersten Fassung schon geändert.
Die Anbindung hier ist deshalb bewusst nachgiebig gebaut: unbekannte
Felder werden übersprungen, fehlende ergeben leere Werte, und im Zweifel
tut ein Hook lieber nichts als das Falsche. Eine Sitzung fällt dadurch
nie aus, aber es kann sein, dass nach einem Update von Antigravity
zunächst weniger ankommt als vorher.

Der erste Verdacht in so einem Fall:

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py doctor
```

Und danach ein Blick darauf, ob die Werkzeugnamen noch passen, siehe
oben.
