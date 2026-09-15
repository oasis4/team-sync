# team-sync

Ein Plugin, das den Arbeitsstand zwischen mehreren Personen teilt, die am
selben Repository arbeiten, jede in ihrer eigenen Session. Läuft unter
Claude Code und unter [Google Antigravity](docs/ANTIGRAVITY.md), auch
gemischt im selben Team.

Wer zu mehreren mit Claude Code an einem Repo arbeitet, kennt beide
Probleme: Jede neue Session fängt bei null an, Architekturentscheidungen
und Konventionen müssen ständig neu erklärt werden. Und keine Session
weiß, was die anderen gerade tun. team-sync legt dafür einen geteilten,
laufend aktualisierten Wissensstand in dasselbe Git-Repository, auf einen
eigenen Branch.

**Kein zentraler Server, keine geteilte KI-Nutzung.** Jede Person nutzt
weiterhin ihre eigene Session mit ihrem eigenen Zugang. Das Plugin
schiebt nur Textdateien über git hin und her.

**Kein gemeinsames Werkzeug nötig.** Wer mit Antigravity arbeitet,
schreibt in denselben Channel wie alle anderen und bekommt dieselben
Meldungen. Der Kanal ist ein Git-Branch mit Markdown darin, und dem ist
gleich, welches Programm ihn beschreibt.

---

## Wie es funktioniert

Neben dem Projektordner liegt ein zweiter Checkout desselben Repos auf
dem Branch `team-channel`, als git worktree:

```
projekte/
├── mein-projekt/           ← hier arbeitest du
└── mein-projekt-channel/   ← Branch team-channel, vom Plugin gepflegt
    ├── status/             eine Datei pro Person
    ├── questions/          eine Datei pro Frage
    ├── decisions/          eine Datei pro Entscheidung
    └── reservierungen/     wer sitzt gerade an welcher Datei
```

Beim **Sessionstart** liest ein Hook den Channel und gibt drei Dinge in
die Session: offene Fragen an dich, woran die anderen zuletzt gearbeitet
haben, und die zuletzt getroffenen Entscheidungen.

**Währenddessen** passieren drei Dinge automatisch:

- **Vor jedem Edit** wird geprüft, ob gerade jemand anders an derselben
  Datei sitzt. Wenn ja, gibt es einen Hinweis — blockiert wird nie.
- **Beim ersten Zugriff** auf eine Datei wird sie für dich reserviert, damit
  die anderen dasselbe sehen.
- **Alle paar Minuten** meldet das Plugin, was im Channel neu dazugekommen
  ist: beantwortete Anfragen, neue Fragen an dich, neue Festlegungen.

Beim **Sessionende** wird ein letzter Stand geschrieben und alle deine
Reservierungen werden freigegeben.

Jede Person, jede Frage und jede Entscheidung ist eine eigene Datei.
Dadurch entstehen praktisch nie Merge-Konflikte, auch wenn drei Leute
gleichzeitig pushen.

### Warum das während der Session passieren muss

`SessionEnd` feuert erst, wenn eine Session wirklich endet. Wer morgens
eine Session öffnet und bis mittags durcharbeitet, stünde im Channel den
ganzen Vormittag mit dem Stand von gestern — und würde von den anderen in
dieser Zeit nichts erfahren.

Bei langen, autonom laufenden Sessions ist der Empfänger einer Meldung
ohnehin nicht der Mensch vor dem Bildschirm, sondern Claude selbst. Genau
deshalb sind die Meldungen als Handlungsanweisungen formuliert und nicht
als Rückfragen: Es ist niemand da, der antworten könnte.

### Was passiert, wenn eine Datei belegt ist

Warten kostet genau die Zeit, die das Werkzeug sparen soll. Deshalb wartet
niemand:

```
14:32  Session A fasst auth.py an → Reservierung
14:51  Session B will an dieselbe Datei
       → Hinweis, B legt eine Anfrage ab und macht mit etwas anderem weiter
14:53  A sieht die Anfrage und antwortet: "Ich bin nur in verify_token"
14:56  B sieht die Antwort und arbeitet an der richtigen Stelle weiter
```

Bleibt eine Antwort aus — weil die andere Session längst geschlossen ist —
gilt die Datei nach zehn Minuten als frei.

Reservierungen auf **verschiedenen Branches** ergeben nur einen knappen
Hinweis. Dort löst git den Konflikt später ohnehin, und eine Warnung, die
zu oft danebenliegt, wird nach dem dritten Mal überlesen.

---

## Installation

Drei Schritte. Die ersten beiden sind für alle gleich, im dritten
unterscheidet sich, womit du arbeitest.

### 1. Dieses Repo klonen

```bash
git clone https://github.com/oasis4/team-sync.git ~/werkzeuge/team-sync
```

Der Klon bleibt liegen, die Hooks rufen die Skripte von dort auf. Wer
ihn später verschiebt, führt Schritt 3 noch einmal aus.

### 2. Channel einrichten

Einmal pro Person und Projekt, im Projekt-Repo ausgeführt:

```bash
cd /pfad/zu/deinem/projekt
python3 ~/werkzeuge/team-sync/scripts/setup_channel.py
```

Die erste Person legt damit den Branch `team-channel` an, alle weiteren
checken ihn nur noch aus. Daneben entsteht ein Ordner
`<projekt>-channel`, das ist der Worktree, in dem die Notizen liegen.

### 3. Das eigene Programm einrichten

#### Claude Code

In der laufenden Session:

```
/plugin marketplace add oasis4/team-sync
```

```
/plugin install team-sync@team-sync-marketplace
```

Danach eine neue Session starten. Hooks und Slash-Commands sind damit
verdrahtet.

#### Antigravity

Antigravity kennt das Pluginformat von Claude Code nicht, es liest
Hooks, Regeln und Workflows aus eigenen Dateien. Ein Skript legt sie an,
im Projekt ausgeführt:

```bash
cd /pfad/zu/deinem/projekt
python3 ~/werkzeuge/team-sync/scripts/setup_antigravity.py
```

Das schreibt in den Projektordner:

```
.agents/
├── hooks.json          Gruppe "team-sync", verweist auf den Klon aus Schritt 1
├── rules/team-sync.md  Dauerregel, erklärt dem Agenten den Channel
└── workflows/          team, ask, answer, decide, sync
```

Danach **Antigravity einmal neu starten**, sonst greifen die Hooks nicht.

Eine bestehende `hooks.json` wird nicht überschrieben. Das Skript liest
sie ein, legt eine Sicherungskopie daneben und ergänzt nur die eigene
Gruppe. Ist sie kein lesbares JSON, bricht es ab und ändert nichts.

**Wichtig für die Zusammenarbeit:** In diesen Dateien stehen absolute
Pfade zu deinem Klon. Sie gehören deshalb nicht ins Repository, sonst
zeigen sie auf dem Rechner der nächsten Person ins Leere. Trag den
Ordner einmal in die `.gitignore` deines Projekts ein:

```bash
echo ".agents/" >> .gitignore
```

Wer das nicht will, nimmt stattdessen `--global`. Dann landet alles
unter `~/.gemini/config/` und gilt für alle Projekte, auch für die ohne
Channel. Dort steigen die Hooks sofort wieder aus, es kostet nur einen
Prozessstart pro Modellaufruf.

Weitere Optionen von `setup_antigravity.py`:

| Option | Wirkung |
|---|---|
| `--global` | Nach `~/.gemini/config/` statt in den Projektordner |
| `--dir <pfad>` | Anderer Ort für den `.agents`-Ordner |
| `--python <befehl>` | Anderer Python-Aufruf in den Hooks, etwa `py -3` |
| `--dry-run` | Zeigt nur, was passieren würde |
| `--entfernen` | Nimmt alles wieder heraus |

Wie die Ereignisse zugeordnet sind und wo die Grenzen liegen, steht in
[docs/ANTIGRAVITY.md](docs/ANTIGRAVITY.md).

### Prüfen, ob es sitzt

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py doctor
```

Der Bericht nennt Channel, Remote, den eigenen Namen und am Ende den
Stand der Antigravity-Seite. Zeigt ein Hook auf eine Datei, die es nicht
gibt, steht das dort als Problem. Genau das passiert, wenn der Klon aus
Schritt 1 verschoben wurde.

Wer lieber das über `/plugin` installierte Plugin statt des Klons nutzt:
Es liegt unter `~/.claude/plugins/marketplaces/`, der genaue Ordnername
steht in `~/.claude/plugins/installed_plugins.json`.

### Voraussetzungen

- Python 3.9 oder neuer, als `python3` aufrufbar
- git 2.5 oder neuer
- Ein gemeinsames Remote, auf das alle pushen dürfen

Keine Pakete zu installieren, das Plugin nutzt nur die
Standardbibliothek.

Heißt der Python-Befehl bei dir `python` statt `python3`: Unter Claude
Code passt du die Zeilen in [hooks/hooks.json](hooks/hooks.json) an,
unter Antigravity übergibst du `--python python` beim Einrichten.

---

## Im Alltag

| Command | Wofür |
|---|---|
| `/team` | Wer arbeitet gerade woran, was ist offen |
| `/ask max wie läuft die Session-Verwaltung im Frontend` | Frage für Max hinterlegen |
| `/answer` | Offene Fragen an dich durchgehen und beantworten |
| `/decide JWT statt Server-Session` | Entscheidung mit Begründung protokollieren |
| `/sync` | Sofort einen selbst formulierten Stand pushen |

Unter Antigravity heißen dieselben fünf Befehle genauso, sie liegen dort
als Workflows unter `.agents/workflows/`.

Reservierungen laufen ohne Zutun. Wer sie von Hand ansehen oder aufheben
will:

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py reservierungen
```

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py freigeben --alle
```

Der Unterschied zwischen `/sync` und dem automatischen Zwischenstand ist
der Punkt: Das Hintergrundskript kennt nur die letzte Nachricht und die
Liste angefasster Dateien. Bei `/sync` schreibt Claude die
Zusammenfassung aus dem vollen Sessionkontext — was fertig ist, was
halbfertig, was als Nächstes kommt. Sinnvoll, wenn gerade ein größerer
Schritt fertig geworden ist.

Alles im Channel sind normale Markdown-Dateien. Sie lassen sich von Hand
bearbeiten, im Editor lesen und auf GitHub im Branch `team-channel`
ansehen.

---

## Einstellungen

Alles optional, per Umgebungsvariable:

| Variable | Vorgabe | Wirkung |
|---|---|---|
| `TEAM_AGENT_NAME` | `git config user.name` | Eigener Name im Channel |
| `TEAM_SYNC_CHECKPOINT_SECONDS` | `600` | Abstand der automatischen Zwischenstände |
| `TEAM_SYNC_EMPFANG_SECONDS` | `120` | Wie oft nach Neuem im Channel gesehen wird |
| `TEAM_SYNC_RESERVIERUNG_STUNDEN` | `4` | Wie lange eine Reservierung gilt |
| `TEAM_SYNC_ANFRAGE_TIMEOUT` | `10` | Minuten, bis eine unbeantwortete Anfrage aufgegeben wird |
| `TEAM_SYNC_ANFRAGE_SPERRE` | `60` | Minuten, bis zu derselben Datei erneut gefragt werden darf |
| `TEAM_SYNC_CHANNEL_DIR` | Worktree bzw. `<projekt>-channel` | Anderer Ort für den Channel |
| `TEAM_SYNC_BRANCH` | `team-channel` | Anderer Branchname |
| `TEAM_SYNC_STALE_HOURS` | `48` | Ab wann ein Status als veraltet gilt |
| `TEAM_SYNC_MAX_STATUS` | `5` | Wie viele fremde Stände in den Sessionkontext kommen |
| `TEAM_SYNC_MAX_DECISIONS` | `5` | Wie viele Entscheidungen in den Sessionkontext kommen |
| `TEAM_SYNC_MAX_QUESTIONS` | `5` | Wie viele offene Fragen in den Sessionkontext kommen |
| `TEAM_SYNC_MAX_STATUS_CHARS` | `700` | Maximale Länge eines fremden Standes im Kontext |
| `TEAM_SYNC_MAX_FILES` | `12` | Wie viele Dateien ein Status auflistet |
| `TEAM_SYNC_CACHE_SECONDS` | `60` | Gültigkeit des internen Cache für Name und Branch |
| `TEAM_SYNC_PROJECT_DIR` | aus der Hook-Nutzlast | Projektordner, falls er nicht selbst gefunden wird |
| `TEAM_SYNC_HOST` | wird erkannt | `claude` oder `antigravity`, falls die Erkennung danebenliegt |
| `TEAM_SYNC_AG_EDIT_TOOLS` | – | Antigravity: Namen der schreibenden Werkzeuge, durch Komma getrennt. Ohne Angabe wird der Name geraten. |
| `TEAM_SYNC_AG_START_SECONDS` | `43200` | Antigravity: ab wann eine Unterhaltung wieder als neu gilt |
| `TEAM_SYNC_POSTFACH_SECONDS` | `900` | Antigravity: wie lange ein zurückgestellter Hinweis gültig bleibt |
| `TEAM_SYNC_FORCE` | – | Auf `1` gesetzt umgeht der Zwischenstand die Drosselung. Zum Ausprobieren gedacht, nicht für den Dauerbetrieb. |

Die `MAX_`-Werte begrenzen, was bei jedem Sessionstart an Tokens anfällt.
Wächst der Channel über Monate, wächst der Kontext nicht mit.

Die drei wichtigsten Stellschrauben im Alltag sind
`TEAM_SYNC_EMPFANG_SECONDS` (wie schnell ihr voneinander erfahrt),
`TEAM_SYNC_RESERVIERUNG_STUNDEN` (zu lang erzeugt Fehlalarme, zu kurz
verpasst Kollisionen) und `TEAM_SYNC_ANFRAGE_TIMEOUT`.

---

## Was es bewusst nicht tut

**Kein Echtzeit-Chat.** Zwei Sessions stimmen sich über git ab, nicht über
eine Leitung. Zwischen Frage und Antwort liegen typischerweise ein paar
Minuten. Das reicht für den Fall, um den es geht — „A sitzt seit zwanzig
Minuten an dieser Datei" — und nicht für „beide greifen in derselben
Sekunde zu". Letzteres soll es auch nicht abfangen.

**Kein Blockieren.** Der Hinweis vor einem Edit verweigert nichts, er
informiert. Ein Hook, der zu oft verweigert, bringt eine autonom laufende
Session stundenlang unbemerkt zum Stehen — das wäre schlimmer als die
doppelte Arbeit, die er verhindern soll.

**Keine KI-Zusammenfassung im Hintergrund.** Der automatische Status wird
aus dem Transkript zusammengesetzt, ohne zusätzlichen Modellaufruf. Jede
Person bezahlt ihr Kontingent selbst, und ein Hintergrundskript, das
ungefragt davon abzwackt, wäre ein schlechter Tausch für eine
Statuszeile. Wer eine echte Zusammenfassung will, nimmt `/sync`.

**Keine automatische Schnittstellendokumentation.** Ein `contracts/`
Ordner für API-Verträge war geplant, ist aber bewusst zurückgestellt,
bis sich der Rest im Alltag bewährt hat.

**Kein Erzwingen.** Die Hooks informieren, sie verhindern nicht, dass
zwei Leute dieselbe Datei anfassen. Das bleibt Teamsache — das Werkzeug
macht nur wahrscheinlicher, dass es rechtzeitig auffällt.

**Keine Gleichbehandlung um jeden Preis.** Unter Antigravity kommt der
Hinweis auf eine belegte Datei einen Schritt später als unter Claude
Code, und der automatische Status ist dort etwas gröber. Warum das so
ist und was es praktisch bedeutet, steht in
[docs/ANTIGRAVITY.md](docs/ANTIGRAVITY.md).

---

## Empfohlener Rollout

1. **Woche 1:** Zu dritt nur mit `status/` und `questions/` arbeiten.
   Das ist der Teil, der sofort etwas bringt.
2. **Danach:** `decisions/` dazunehmen. Das zahlt sich erst nach einigen
   Wochen aus, wenn jemand eine alte Entscheidung nachschlägt.
3. **Später:** `contracts/`, falls sich das Grundsystem bewährt.

Wichtig für die Aktualität: Das System ist nur so frisch wie euer
Push-Rhythmus. Kleine, häufige Commits helfen mehr als stundenlange
Sessions am Stück.

---

## Mitarbeit

Fehlerberichte und Vorschläge gerne als Issue. Zum Entwickeln siehe
[CONTRIBUTING.md](CONTRIBUTING.md).

```bash
python3 -m unittest discover -s tests -t tests
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).
