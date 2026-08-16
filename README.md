# team-sync

Ein Claude-Code-Plugin, das den Arbeitsstand zwischen mehreren Personen
teilt, die am selben Repository arbeiten — jede in ihrer eigenen Session.

Wer zu mehreren mit Claude Code an einem Repo arbeitet, kennt beide
Probleme: Jede neue Session fängt bei null an, Architekturentscheidungen
und Konventionen müssen ständig neu erklärt werden. Und keine Session
weiß, was die anderen gerade tun. team-sync legt dafür einen geteilten,
laufend aktualisierten Wissensstand in dasselbe Git-Repository, auf einen
eigenen Branch.

**Kein zentraler Server, keine geteilte KI-Nutzung.** Jede Person nutzt
weiterhin ihre eigene Claude-Code-Session mit ihrer eigenen Membership.
Das Plugin schiebt nur Textdateien über git hin und her.

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
    └── decisions/          eine Datei pro Entscheidung
```

Beim **Sessionstart** liest ein Hook den Channel und gibt drei Dinge in
die Session: offene Fragen an dich, woran die anderen zuletzt gearbeitet
haben, und die zuletzt getroffenen Entscheidungen.

**Währenddessen** schreibt ein Hook nach jeder Antwort gedrosselt einen
Zwischenstand — höchstens alle zehn Minuten, sonst gäbe es einen Commit
pro Nachricht. Beim **Sessionende** wird ein letzter Stand geschrieben.

Jede Person, jede Frage und jede Entscheidung ist eine eigene Datei.
Dadurch entstehen praktisch nie Merge-Konflikte, auch wenn drei Leute
gleichzeitig pushen.

### Warum der Zwischenstand nötig ist

`SessionEnd` feuert erst, wenn eine Session wirklich endet. Wer morgens
eine Session öffnet und sie bis abends offenlässt, stünde im Channel den
ganzen Tag mit dem Stand von gestern. Für ein Werkzeug, das zeigen soll,
wer gerade woran sitzt, wäre genau das der entscheidende Fehler — deshalb
der zusätzliche, gedrosselte `Stop`-Hook.

---

## Installation

### 1. Plugin installieren

In Claude Code:

```
/plugin marketplace add oasis4/team-sync
```

```
/plugin install team-sync@team-sync-marketplace
```

### 2. Channel einrichten

Einmal pro Person und Projekt. Das Setup-Skript hängt nicht am Plugin,
es braucht nur git — am einfachsten aus einem Klon dieses Repos, im
Projekt-Repo ausgeführt:

```bash
git clone https://github.com/oasis4/team-sync.git ~/werkzeuge/team-sync
```

```bash
cd /pfad/zu/deinem/projekt && python3 ~/werkzeuge/team-sync/scripts/setup_channel.py
```

Die erste Person legt damit den Branch `team-channel` an, alle weiteren
checken ihn nur noch aus. Danach läuft alles automatisch.

Prüfen, ob es sitzt:

```bash
python3 ~/werkzeuge/team-sync/scripts/team_sync.py doctor
```

Wer lieber das installierte Plugin nutzt: Es liegt unter
`~/.claude/plugins/marketplaces/`, der genaue Ordnername steht in
`~/.claude/plugins/installed_plugins.json`.

### Voraussetzungen

- Python 3.8 oder neuer, als `python3` aufrufbar
- git 2.5 oder neuer
- Ein gemeinsames Remote, auf das alle pushen dürfen

Keine Pakete zu installieren, das Plugin nutzt nur die
Standardbibliothek.

Heißt der Python-Befehl bei dir `python` statt `python3`, passe die drei
Zeilen in [hooks/hooks.json](hooks/hooks.json) entsprechend an.

---

## Im Alltag

| Command | Wofür |
|---|---|
| `/team` | Wer arbeitet gerade woran, was ist offen |
| `/ask max wie läuft die Session-Verwaltung im Frontend` | Frage für Max hinterlegen |
| `/answer` | Offene Fragen an dich durchgehen und beantworten |
| `/decide JWT statt Server-Session` | Entscheidung mit Begründung protokollieren |
| `/sync` | Sofort einen selbst formulierten Stand pushen |

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
| `TEAM_SYNC_CHANNEL_DIR` | Worktree bzw. `<projekt>-channel` | Anderer Ort für den Channel |
| `TEAM_SYNC_BRANCH` | `team-channel` | Anderer Branchname |
| `TEAM_SYNC_STALE_HOURS` | `48` | Ab wann ein Status als veraltet gilt |
| `TEAM_SYNC_MAX_STATUS` | `5` | Wie viele fremde Stände in den Sessionkontext kommen |
| `TEAM_SYNC_MAX_DECISIONS` | `5` | Wie viele Entscheidungen in den Sessionkontext kommen |

Die letzten beiden begrenzen, was bei jedem Sessionstart an Tokens
anfällt. Wächst der Channel über Monate, wächst der Kontext nicht mit.

---

## Was es bewusst nicht tut

**Kein Echtzeit-Chat.** Zwei gleichzeitig laufende Sessions reden nicht
miteinander. Der Austausch passiert beim Sessionstart und bei jedem
Zwischenstand, nicht live.

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
