# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/).

## [0.5.0] — 2026-11-02

Bis hierher hat team-sync im Alltag weniger getan, als die Tests
behaupteten. Die meisten Fehler hatten denselben Ursprung: Die
Testumgebung setzte einen Kurznamen und `CLAUDE_PLUGIN_ROOT`, und beides
ist im echten Betrieb nicht so. Zwei weitere zeigten sich erst in einer
Simulation mit zwei echten Claude-Code-Sitzungen. Diese Version behebt sie und übernimmt dazu,
was das [Hackathon-Board](https://github.com/azizu06/hackathon-agent-board)
besser macht: Agenten, die einander Nachrichten schreiben und sich
gegenseitig wecken.

### Behoben

- **Fragen kamen nicht an.** `/ask max` legte die Frage unter `max` ab,
  Max steht im Channel aber unter seinem git-Namen `max-mustermann`. Die
  Frage blieb ungelesen liegen, ohne jede Meldung. Namen werden jetzt
  gegen die bekannten Personen aufgelöst, Vor- oder Nachname genügen.
  Ein mehrdeutiger Name bricht mit den Kandidaten ab, ein unbekannter
  wird laut gemeldet.
- **Befehle aus Hook-Hinweisen liefen ins Leere.** Der Hinweis auf eine
  belegte Datei und der Rückkanal nannten `${CLAUDE_PLUGIN_ROOT}` oder
  gar keinen Pfad. In Claudes Shell ist die Variable nicht gesetzt, der
  Befehl wurde zu `python3 "/scripts/team_sync.py"`. Damit kam keine
  einzige Dateianfrage je zustande. Die Hinweise nennen jetzt den echten
  Pfad.
- **Das Sessionende kam nie an.** Claude Code gibt SessionEnd-Hooks
  anderthalb Sekunden, und ein Timeout aus einem Plugin hebt das nicht
  an. Status und Freigabe brauchten länger, die Reservierungen blieben
  vier Stunden stehen. Der Hook löst die Arbeit jetzt in einen eigenen
  Prozess ab und kehrt sofort zurück.
- **Antworten auf normale Fragen erreichten den Fragenden nicht.** Der
  Rückkanal kannte nur Antworten auf Dateianfragen. Jetzt kommen alle
  Antworten, während der Session und beim nächsten Start.
- **Der Hinweis vor einem Edit hat die Rechte umgangen.** Er antwortete
  mit `permissionDecision: "allow"`. Das überspringt die Rückfrage, ob
  Claude die Datei bearbeiten darf, ausgerechnet bei Dateien, an denen
  gerade jemand anders saß. Der Hook greift jetzt nicht mehr in die
  Rechte ein.
- **Der Hinweis vor einem Edit kam zu spät.** Ein Begleittext erreicht
  Claude erst mit dem Ergebnis des Werkzeugs, also nach dem Edit. Jetzt
  wird der erste Edit an einer belegten Datei einmal angehalten, mit
  Begründung und dem fertigen Befehl für eine Anfrage. Der nächste
  Versuch geht durch. Abschaltbar mit `TEAM_SYNC_ANHALTEN=aus`.
- **Die erste Person im Team bekam keine Regeln.** Solange von den
  anderen nichts im Channel lag, blieb der Startkontext leer, und damit
  fehlte genau der Hinweis, den anderen Bescheid zu sagen.
- Der SessionEnd-Hook las das Feld `session_end_reason`, das es nicht
  gibt. Es heißt `reason`. Ein `/clear` galt deshalb als Sessionende.
- Gleichzeitige Pulls mehrerer Prozesse konnten sich gegenseitig den
  Rebase abbrechen. Alle Pulls außerhalb eines Schreibvorgangs laufen
  jetzt unter der Channel-Sperre.

### Neu

- **Nachrichten mit @name.** `/post @max Login ist gemergt, die Route
  ist frei` legt eine Nachricht in `nachrichten/` ab. Gemeldet wird sie
  nur an die Genannten, ohne `@name` an alle. Für Übergaben, für
  Änderungen, von denen andere abhängen, und für Blocker.
- **Der Lauscher.** Ein Plugin-Monitor schaut alle 45 Sekunden mit
  `git ls-remote` nach, ob sich der Channel bewegt hat, zieht nur dann,
  und meldet, was für die Session neu ist. Die Meldung erreicht Claude
  auch, wenn die Session auf Eingabe wartet. Abschaltbar mit
  `TEAM_SYNC_LAUSCHEN=aus`.
- **`team_sync.py warten`** kehrt bei der ersten Meldung zurück, wie
  `tools/board wait` beim Hackathon-Board. Für andere Agenten und für
  Schleifen.
- **Hook vor jeder Eingabe** (UserPromptSubmit). Liest nur den lokalen
  Stand, ohne Netz.
- **Verhaltensregeln in jeder Meldung**, übernommen vom Board: zügig
  antworten, nie nur bestätigen, der eigene Mensch geht vor.
- **Teammitglieder direkt fragen.** Im Startkontext steht jetzt, dass
  Claude bei Bedarf das Teammitglied mit /ask fragt, statt den eigenen
  Nutzer als Boten zu benutzen. In der Simulation hat Claude genau das
  sonst getan.
- **`tests/szenario.py`** spielt einen ganzen Ablauf zweier Sitzungen
  durch, mit echten Hooks, echten Lauschern und echtem Remote, und
  misst, wie lange jede Meldung braucht.
- `team_sync.py nachrichten` listet die letzten Nachrichten,
  `/team` zeigt sie ebenfalls.
- Fragen an `alle` gehen an das ganze Team.
- Das Setup trägt die eigene Person mit Namen in den Channel ein, damit
  andere sie finden, bevor sie die erste Session geöffnet hat.
- `doctor` nennt die bekannten Personen und ob ein Lauscher läuft.

### Geändert

- Reservieren (PostToolUse) und Zwischenstand (Stop) laufen im
  Hintergrund. Claude wartet nicht mehr auf einen Push.
- Der Stop-Hook ist in zwei Einträge geteilt, `empfang` synchron und
  `schreiben` im Hintergrund. Er zieht nur noch selbst, wenn kein
  Lauscher läuft.
- `TEAM_SYNC_EMPFANG_SECONDS` steuert nur noch, wie oft der Stop-Hook
  zieht. Gelesen wird bei jedem Aufruf, weil Lesen billig ist.
- Antigravity bekommt den Workflow `post` und dieselben Regeln. Einen
  Lauscher gibt es dort nicht.

### Bekannte Grenzen

- Bei `/exit` fragt Claude Code einmal nach, weil der Lauscher als
  Hintergrundarbeit zählt. Enter bestätigt. Aus einem Plugin heraus
  lässt sich das nicht abstellen.
- Jede Meldung des Lauschers ist ein Modellaufruf auf dem Kontingent
  der Person, die sie bekommt. Gemeldet wird deshalb nur, was an sie
  oder an alle geht, und jede Sache nur einmal.
- Monitore laufen nicht mit `claude -p` und nicht in älteren
  Claude-Code-Versionen. Dann bleibt es bei den Hooks.
- Arbeitet eine Person mit zwei Sessions im selben Projektordner, sieht
  nur eine von beiden jede Meldung. Die Merkliste gilt pro Projekt,
  nicht pro Session.

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
- `setup_antigravity.py` erinnert daran, `.agents/` in die `.gitignore`
  des Projekts zu setzen. In den geschriebenen Dateien stehen absolute
  Pfade; landen sie im Repository, zeigen sie bei der nächsten Person
  ins Leere und ihre Hooks tun still nichts.
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

### Behoben

- **Zwei Tests hingen am echten Benutzerverzeichnis.** Die globale
  Einrichtung liegt unter `~/.gemini/config`, und die Tests dazu haben
  genau dort gelesen und geschrieben. Unter Windows hat das Verbiegen
  von `HOME` nichts genützt, weil `Path.home()` dort `USERPROFILE`
  liest, und der Testlauf hat die tatsächliche Konfiguration des
  Entwicklers angefasst. Der Ort ist jetzt über `TEAM_SYNC_GEMINI_DIR`
  umlenkbar, und die Testumgebung setzt ihn immer.
- **`doctor` hat unter Windows den falschen Pfad gemeldet.** Ein Hook,
  der auf `/gibt/es/nicht/x.py` zeigt, wurde als `\gibt\es\nicht\x.py`
  ausgegeben. Wer damit in seiner `hooks.json` sucht, findet nichts.
  Gemeldet wird jetzt, was dort wirklich steht.

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
