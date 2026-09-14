# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/).

## [0.4.0] — 2026-09-14

Bis hierher setzte team-sync voraus, dass alle im Team dasselbe Programm
benutzen. Das ist eine Annahme, die bei der ersten neuen Person kippt.
Der Kanal selbst hat nie davon abgehangen, er ist ein Git-Branch mit
Markdown darin, aber die Hooks sprachen nur ein Protokoll.

Diese Version trennt beides. Wer mit Google Antigravity arbeitet, sitzt
ab jetzt im selben Channel wie alle anderen, sieht dieselben
Reservierungen und bekommt dieselben Meldungen.

### Neu

- **Antigravity als zweites Hostprogramm.** Eigene Hooks, eigene
  Dauerregel, dieselben fünf Befehle als Workflows. Eingerichtet mit
  `scripts/setup_antigravity.py`, beschrieben in
  [docs/ANTIGRAVITY.md](docs/ANTIGRAVITY.md).
- **Host-Abstraktion in `lib/host.py`.** Die einzige Stelle, die weiß,
  welches Programm gerade läuft. Sie liest beide Nutzlastformate, gibt
  jedem seine eigene Antwortform und sorgt dafür, dass der Rest des
  Plugins hostneutral bleibt.
- **Zurückgestellte Hinweise.** Antigravity erwartet vor einem
  Werkzeugaufruf genau eine Erlaubnis und sonst nichts. Der Hinweis auf
  eine belegte Datei wird deshalb abgelegt und beim nächsten
  Modellaufruf nachgereicht, statt ein Feld zu senden, das der Parser
  ablehnen könnte.
- **Feld `werkzeug` im Status.** Die Übersicht zeigt jetzt, wer mit
  welchem Programm arbeitet. Eine Lesehilfe, keine Statistik: Eine
  Reservierung aus einem anderen Werkzeug kann träger sein, und das soll
  niemand für einen Fehler halten.
- `doctor` berichtet, ob und wo die Antigravity-Seite eingetragen ist,
  und meldet Hooks, die ins Leere zeigen. Das passiert, sobald der Klon
  verschoben wird, denn dort stehen absolute Pfade.

### Geändert

- **Die Dateiliste im Status hängt nicht mehr am Transkript.** Sie
  entsteht aus den eigenen Hooks und ist damit unter jedem Programm
  gleich verlässlich. Das Transkript bleibt die erste Quelle, weil es
  auch Dateien von vor dem Einrichten des Channels kennt.
- **Die Transkriptauswertung hat einen zweiten Weg.** Liefert das
  bekannte Format nichts, wird nachgiebig nach Nutzertext gesucht, ohne
  eine Struktur vorauszusetzen. Findet auch das nichts, wird der Status
  dünner statt leer.
- `TEAM_SYNC_PROJECT_DIR` steht jetzt vor `CLAUDE_PROJECT_DIR`. Unter
  Antigravity gibt es kein Gegenstück, der Projektordner kommt dort aus
  der Hook-Nutzlast.

### Bekannte Grenzen

- Unter Antigravity kommt der Hinweis auf eine belegte Datei einen
  Schritt später als unter Claude Code. Der Grund steht oben.
- Die Namen der schreibenden Werkzeuge liegen dort nicht fest. Das
  Plugin rät über den Namen und verlangt zusätzlich einen Dateipfad im
  Aufruf. Wer die Namen seiner Installation kennt, setzt
  `TEAM_SYNC_AG_EDIT_TOOLS`.

## [0.3.0] — 2026-08-17

Bis hierher war team-sync ein Logbuch: Es hielt fest, was passiert ist,
und wurde einmal beim Sessionstart gelesen. Wer morgens eine Session
öffnete und bis mittags durcharbeitete, erfuhr in der Zwischenzeit
nichts. Der Kanal war gebaut, der Empfänger fehlte.

Diese Version macht daraus etwas, das sich meldet, wenn es darauf
ankommt — gedacht für lange, autonom laufende Sessions, in denen der
Empfänger einer Meldung nicht der Mensch am Bildschirm ist, sondern
Claude selbst.

### Neu

- **Reservierungen.** Beim ersten Zugriff auf eine Datei wird sie für
  die eigene Session reserviert. Ein `PostToolUse`-Hook erledigt das,
  aber nur beim ersten Mal — sonst entstünde ein Commit pro Edit.
- **Warnung vor dem Edit.** Ein `PreToolUse`-Hook meldet, wenn gerade
  jemand anders an derselben Datei sitzt. Er **blockiert nie**: Ein Hook,
  der zu oft verweigert, bringt eine autonome Session stundenlang
  unbemerkt zum Stehen. Auf verschiedenen Branches gibt es nur einen
  knappen Hinweis, weil git das später ohnehin löst.
- **Dateianfragen.** Statt zu warten, legt die zweite Session eine
  Anfrage ab und arbeitet sofort weiter. Die erste beantwortet sie oft
  genauer, als ein Mensch es könnte — sie weiß, an welcher Stelle sie
  gerade arbeitet. Bleibt die Antwort aus, gilt die Datei nach zehn
  Minuten als frei; die Gegenseite kann eine tote Session sein.
- **Rückkanal in laufende Sessions.** Beantwortete Anfragen, neue Fragen
  und neue Festlegungen werden während der Arbeit gemeldet, nicht erst
  beim nächsten Start. Gemeldet wird nur, was noch nicht gesehen wurde —
  eine Meldung, die sich wiederholt, wird nach dem zweiten Mal ignoriert.
- Neue Kommandos `anfrage`, `freigeben` und `reservierungen`.
- Reservierungen werden beim Sessionende freigegeben und verfallen nach
  vier Stunden.

### Behoben

- **Die Anfragesperre griff nie.** Sie hing an einer Sitzungskennung,
  die der Hook aus seiner Payload kennt und das Kommandozeilenwerkzeug
  nicht — zwei verschiedene Schlüssel, ein wirkungsloser Riegel. Im
  Alltag hätte das eine Anfrage pro Edit erzeugt. Die Sperre hängt jetzt
  an der Zeit.
- **Absolute Pfade in Reservierungen.** Schlug die Relativierung fehl,
  reservierte Person A `C:/Users/lars/projekt/auth.py`, während Person B
  nach `/home/max/projekt/auth.py` suchte — dieselbe Datei, zwei
  Einträge, Kollision unentdeckt. Jetzt mit zweitem Weg über einen
  Vergleich ohne Rücksicht auf Groß- und Kleinschreibung.
- Drei Einstellungen aus `render.py` waren nie dokumentiert. Der
  entsprechende Test prüfte nur ein einziges Modul.

### Geändert

- `SUBDIRS` enthält `reservierungen/`. Bestehende Channels bekommen den
  Ordner beim nächsten Schreibzugriff.
- Ein Cache für Name, Branch und Channel-Pfad im Git-Verzeichnis. Ohne
  ihn bräuchte der Hook vor jedem Edit drei git-Aufrufe.

## [0.2.0] — 2026-08-16

Erste vollständige Fassung. Der Prototyp 0.1.0 hatte die Struktur, aber
mehrere Fehler, die im Alltag zu dritt aufgefallen wären.

### Behoben

- **Der Sessionstart-Kontext kam nie an.** Der Hook gab
  `{"additionalContext": …}` auf oberster Ebene aus. Claude Code erwartet
  das Feld unter `hookSpecificOutput`, also wurde die Ausgabe verworfen —
  die Kernfunktion des Plugins lief ins Leere.
- **Namen mit Umlauten ergaben kaputte Dateinamen.** `slugify` enthielt
  `text.replace("ae", "ae")`, also gar keine Ersetzung. Aus „Jörg Müller"
  wurde `j-rg-m-ller`, und Fragen an diese Person kamen nie an.
- **Abgelehnte Pushs gingen still verloren.** Pushte jemand zwischen Pull
  und Push, blieb der eigene Status unbemerkt lokal liegen. Jetzt wird
  rebased und erneut versucht.
- **Die Drosselung schlug in einem Worktree fehl.** Die Markerdatei wurde
  unter `<projekt>/.git/` erwartet. In einem Worktree ist `.git` eine
  Datei, kein Verzeichnis. Der Pfad kommt jetzt von
  `git rev-parse --absolute-git-dir`.
- **Empfänger einer Frage wurden per Volltextsuche gesucht.** Das traf
  auch auf Fragen zu, in deren Fließtext ein Name vorkam. Jetzt ein
  klar abgegrenztes Kopffeld.
- **Das Setup scheiterte mit git vor 2.42.** `git worktree add --orphan`
  gibt es erst ab dieser Version. Der verwaiste Branch entsteht jetzt
  über `commit-tree`, was seit Jahren unverändert funktioniert.
- **Das Setup scheiterte unter Python 3.9.** Das Argument für
  Zeilenenden in `Path.write_text` gibt es erst ab 3.10. Alle Dateien
  laufen jetzt über eine gemeinsame Schreibfunktion. Aufgefallen ist es
  erst in der CI, weil hier 3.13 lief — im Team laufen aber
  unterschiedliche Versionen.

### Neu

- `team_sync.py`: eine Kommandozeile für alles, was die Slash-Commands
  tun. Die Commands beschreiben nicht mehr git-Aufrufe in Prosa.
- `/team` zeigt, wer woran arbeitet und was offen ist.
- `doctor` prüft die Einrichtung und benennt konkret, was fehlt.
- Kopffelder in allen Channel-Dateien, maschinenlesbar und trotzdem im
  GitHub-Diff lesbar.
- Sperre gegen gleichzeitige Schreibzugriffe mehrerer Sessions auf
  demselben Rechner.
- Statusmeldungen zeigen ihr Alter und werden nach 48 Stunden als
  veraltet markiert.
- Obergrenzen für den Sessionstart-Kontext, damit ein über Monate
  wachsender Channel nicht in jede Session hineinwächst.
- Absolute Dateipfade werden projektrelativ geschrieben.
- Testsuite gegen echte Repositories, inklusive Push-Kollision zwischen
  zwei Personen.

### Geändert

- Der automatische Status nimmt den ursprünglichen Auftrag der Session
  statt nur der letzten Nachricht, und lässt Werkzeugausgaben und
  System-Hinweise weg.
- git-Aufrufe laufen mit `GIT_TERMINAL_PROMPT=0` und ohne geerbte
  Standardeingabe, damit ein Passwortdialog keinen Hook anhält.
- Alle Ein- und Ausgaben laufen über UTF-8, auch auf Windows-Konsolen.

## [0.1.0]

Prototyp: Channel-Struktur, drei Hooks, `/ask`, `/answer`, `/decide`,
`/sync`.
