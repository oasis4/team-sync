# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/).

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
