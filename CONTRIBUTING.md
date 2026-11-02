# Mitarbeit an team-sync

## Aufbau

```
.claude-plugin/     plugin.json und marketplace.json
commands/           die Slash-Commands von Claude Code
hooks/hooks.json    Verdrahtung der Hooks unter Claude Code
monitors/           der Lauscher als Plugin-Monitor
antigravity/
  rules/            Dauerregel für Antigravity
  workflows/        dieselben sechs Befehle als Antigravity-Workflows
scripts/
  lib/
    channel.py      git, Pfade, Namen, Sperre, Drosselung, Cache
    host.py         Unterschiede zwischen Claude Code und Antigravity
    frontmatter.py  Kopffelder der Channel-Dateien
    render.py       Dateiformate und der Sessionstart-Kontext
    transcript.py   Auswertung des Sessiontranskripts
    autostatus.py   gemeinsame Logik der schreibenden Hooks
    reservierung.py wer sitzt an welcher Datei
    anfrage.py      Klärung zwischen zwei Sessions
    empfang.py      der Rückkanal in laufende Sessions
    nachrichten.py  Nachrichten mit @name
    personen.py     wer zum Team gehört, wen ein Name meint
    lauschen.py     die Schleife hinter Monitor und 'warten'
  session_start.py       SessionStart-Hook (Claude Code)
  prompt_submit.py       UserPromptSubmit-Hook, Rückkanal ohne Netz
  session_checkpoint.py  Stop-Hook: Rückkanal und Zwischenstand
  session_end.py         SessionEnd-Hook, löst seine Arbeit ab
  lauschen.py            Plugin-Monitor, weckt die Session
  antigravity_hook.py    PreInvocation, PostInvocation und Stop
  tool_pre_edit.py       PreToolUse-Hook, warnt vor belegten Dateien
  tool_post_edit.py      PostToolUse-Hook, reserviert beim ersten Zugriff
  setup_channel.py       einmaliges Setup des Channels
  setup_antigravity.py   trägt das Plugin in Antigravity ein
  team_sync.py           die Kommandozeile hinter den Commands
tests/              unittest, ohne externe Pakete
```

Die beiden Werkzeug-Hooks laufen unter beiden Programmen. Sie enthalten
keine Fallunterscheidung, weil die in `lib/host.py` steckt.

## Der heiße Pfad

`tool_pre_edit.py` läuft **vor jedem einzelnen Edit**. Dort gilt eine
Regel, die sonst nirgends gilt:

> Kein Netzwerkzugriff, kein git-Aufruf, so früh aussteigen wie möglich.

Name, Branch und Channel-Pfad kommen aus `schneller_kontext()` in
`channel.py`, einem Cache im Git-Verzeichnis. Ein `git pull` an dieser
Stelle wären ein bis drei Sekunden mal hunderte Edits — das erwürgt die
Session. Der Pull läuft stattdessen im `Stop`-Hook mit.

Wird der Hook langsam, fällt das nicht als Fehler auf, sondern nur als
zähe Session, und dann sucht niemand hier. Deshalb misst
`test_hook_laeuft_schnell` die Laufzeit mit.

Dieselbe Regel gilt für `prompt_submit.py`, der vor jeder Eingabe
läuft. Er liest nur den lokalen Stand. Aktuell hält den der Lauscher im
Hintergrund.

## Texte an das Modell nennen echte Pfade

Was ein Hook an Claude zurückgibt, wird nicht mehr ersetzt.
`${CLAUDE_PLUGIN_ROOT}` gilt nur in `hooks.json`, in `monitors.json` und
in den Commands. In einem Hinweistext bleibt die Variable stehen, und in
Claudes Shell ist sie leer. Bis 0.4 lief dadurch kein einziger Befehl
aus einem Hinweis. Für solche Texte gibt es `cli_befehl()` in
`channel.py`, und `test_befehl_aus_dem_hinweis_laeuft_in_einer_shell`
führt den Befehl tatsächlich aus.

## Tests gegen den echten Betrieb

Die Testumgebung setzt `TEAM_AGENT_NAME` und `CLAUDE_PLUGIN_ROOT`. Im
Alltag ist beides nicht so: Der Name kommt aus `git config user.name`,
also meist mit Vor- und Nachnamen, und die Variable fehlt in Claudes
Shell. Wer etwas an Namen oder Befehlen ändert, testet mit
`self.team.anzeigenamen` und ohne die Variable, wie in
`tests/test_live.py`.

## Das Szenario

`tests/szenario.py` spielt einen ganzen Ablauf zweier Sitzungen durch:
Reservierung, angehaltener Edit, Anfrage, Weckruf, Antwort, Nachricht,
Sessionende. Wer an Hooks, Lauscher oder Meldungstexten etwas ändert,
lässt es laufen. Es zeigt Fehler, die einzelne Tests nicht sehen, weil
ein Schritt nur gelingt, wenn der davor wirklich bei der anderen
Sitzung angekommen ist.

## Zwei Sätze, die das Verhalten bestimmen

**Der Hook hält höchstens einmal an.** Sitzt jemand auf demselben
Branch an der Datei, wird der erste Edit einmal mit `deny` und einer
Begründung angehalten, jeder weitere geht durch. Nur so erreicht die
Warnung Claude vor dem Edit, denn `additionalContext` kommt erst mit dem
Ergebnis des Werkzeugs an. Öfter anzuhalten wäre falsch: Ein Hook, der
immer wieder verweigert, bremst eine autonome Session stundenlang, ohne
dass es jemand merkt.

**Der Hook gibt nie `allow` zurück.** Das überspringt die Rückfrage, ob
Claude die Datei bearbeiten darf, und hebelt damit die Einstellungen
des Nutzers aus. Bis 0.5 war genau das so.

**Warten heißt nie Blockieren.** Wer auf eine belegte Datei stößt, legt
eine Anfrage ab und arbeitet weiter. Jede Meldung, die zum Warten
auffordert statt zum Weiterarbeiten, ist ein Fehler im Text.

## Zwei Hostprogramme, eine Sachlogik

`lib/host.py` ist die einzige Stelle, die weiß, welches Programm gerade
läuft. Alles andere arbeitet mit dem normalisierten Ereignis aus
`lies_ereignis()` und mit den Ausgabefunktionen daneben.

Wer einen Hook anfasst, sollte deshalb nicht auf `tool_name` oder
`hookSpecificOutput` zugreifen, sondern auf `daten.werkzeug`,
`daten.datei` und `host.melde_kontext()`. Sonst entsteht ein Hook, der
unter dem einen Programm funktioniert und unter dem anderen still nichts
tut, und still nichts tun ist hier der teuerste Fehlermodus.

Zwei Dinge sind an Antigravity anders und nicht verhandelbar:

1. **Platzhalter werden nicht ersetzt.** In der dortigen `hooks.json`
   stehen absolute Pfade, geschrieben von `setup_antigravity.py`. Wird
   der Klon verschoben, zeigen sie ins Leere, und `doctor` sagt das.
2. **Die Antwort auf `PreToolUse` ist genau `{"decision": "allow"}`.**
   Ein zusätzliches Feld kann der Parser ablehnen. Der Hinweis auf eine
   belegte Datei geht deshalb ins Postfach und wird beim nächsten
   `PreInvocation` nachgereicht.

Das Protokoll dort ist weniger festgeschrieben als das von Claude Code.
Neuer Code auf dieser Seite gehört entsprechend nachgiebig gebaut:
unbekannte Felder überspringen, fehlende als leer behandeln, im Zweifel
nichts tun.

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
4. Denselben Workflow unter `antigravity/workflows/` anlegen, mit
   `{{TEAM_SYNC_ROOT}}` statt `${CLAUDE_PLUGIN_ROOT}`. Ein Test wacht
   darüber, dass beide Listen gleich bleiben.
5. Test in `tests/test_channel.py`.

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
