# Mitarbeit an team-sync

## Aufbau

```
.claude-plugin/     plugin.json und marketplace.json
commands/           die Slash-Commands, je eine Markdown-Datei
hooks/hooks.json    Verdrahtung der drei Hooks
scripts/
  lib/
    channel.py      git, Pfade, Namen, Sperre, Drosselung
    frontmatter.py  Kopffelder der Channel-Dateien
    render.py       Dateiformate und der Sessionstart-Kontext
    transcript.py   Auswertung des Sessiontranskripts
    autostatus.py   gemeinsame Logik der beiden schreibenden Hooks
  session_start.py       SessionStart-Hook
  session_checkpoint.py  Stop-Hook, gedrosselt
  session_end.py         SessionEnd-Hook
  setup_channel.py       einmaliges Setup
  team_sync.py           die Kommandozeile hinter den Commands
tests/              unittest, ohne externe Pakete
```

## Zwei Regeln, die alles andere bestimmen

**1. Keine externen Abhängigkeiten.** Nur die Standardbibliothek. Das
Plugin muss auf dem Rechner jedes Teammitglieds sofort laufen, ohne
`pip install`, ohne virtuelle Umgebung.

**2. Kein Hook darf eine Session blockieren.** Ein Fehler beim Schreiben
des Status ist ärgerlich. Eine Session, die deshalb nicht startet, ist
ein Grund, das Plugin zu deinstallieren. Deshalb:

- Alles, was schiefgehen kann, gibt einen Rückgabewert statt einer
  Exception. `run_git` wirft nie.
- Jedes Hook-Skript hat ein `try/except` um seine gesamte Arbeit.
- git-Aufrufe haben immer einen Timeout und laufen mit
  `GIT_TERMINAL_PROMPT=0`, damit ein Passwortdialog sie nicht anhält.
- Kein git-Aufruf erbt die Standardeingabe des Hooks.

## Arbeitsteilung zwischen Skript und Modell

Alles Wiederkehrende gehört ins Skript: Dateinamen, Kopffelder, Commit,
Push, Wiederholung nach abgelehntem Push. Beim Modell bleibt nur, was ein
Skript nicht kann — den Inhalt formulieren.

Die Slash-Commands sollen deshalb kurz sein. Eine Anweisung wie „ermittle
das Channel-Verzeichnis, führe git pull aus, lege eine Datei an nach dem
Muster …" kostet bei jedem Aufruf Tokens für etwas, das sich nie ändert,
und das Ergebnis hängt davon ab, ob die Schritte diesmal genau befolgt
wurden. Wenn ein Command anfängt, git-Befehle zu beschreiben, gehört das
in `team_sync.py`.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

Einzeln:

```bash
python3 -m unittest tests.test_lib
cd tests && python3 -m unittest test_channel.TestFragen -v
```

Die Tests in `test_channel.py` bauen echte Repositories auf: ein bare
Repo als Remote, dazu einen Klon pro erfundenem Teammitglied, und rufen
die Skripte als Unterprozesse auf, so wie Claude Code es täte.

Das ist langsamer als Attrappen und Absicht. Fast alles, was hier
schiefgehen kann, passiert in git: ein Worktree, der nicht gefunden wird,
ein Push, der abgelehnt wird, weil jemand schneller war, eine Datei, die
versehentlich mitcommittet wird und dann bei jedem Rebase kollidiert.
Nachgebaute git-Antworten würden solche Fälle bestätigen statt sie zu
prüfen — sie sind bei der Entwicklung genau so aufgetaucht.

Ein Test für einen behobenen Fehler soll im Kommentar festhalten, was
schiefging. `test_sessionstart_liefert_gueltiges_hook_json` ist dafür das
Beispiel.

## Neue Kommandos

1. Unterkommando in `team_sync.py` ergänzen, mit einem `cmd_`-Handler und
   einem Eintrag in `build_parser`.
2. Format in `render.py` unterbringen, nicht im Handler.
3. Slash-Command unter `commands/` anlegen, der es aufruft.
4. Test in `tests/test_channel.py`.

## Änderungen am Channel-Format

Die Kopffelder werden von `render.py` gelesen. Ein neues Feld muss
optional sein: Im Team laufen unterschiedliche Plugin-Stände
nebeneinander, und ältere Dateien liegen weiter im Branch. Nichts darf
kaputtgehen, nur weil ein Feld fehlt.

## Stil

- Deutsch in Code-Kommentaren, Dokumentation und Ausgaben, passend zum
  Rest des Projekts.
- Kommentare erklären das Warum. Das Was steht im Code.
- Alle Dateien werden mit `encoding="utf-8"` und `newline="\n"`
  geschrieben, damit der Channel unter Windows und Linux gleich aussieht.
