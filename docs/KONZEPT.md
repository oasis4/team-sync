# Konzept und Entscheidungen

Warum dieses Plugin so gebaut ist, wie es gebaut ist. Festgehalten,
damit die Gründe nachvollziehbar bleiben, wenn später jemand etwas
ändern will.

## Das Problem

Beim Programmieren mit Claude Code geht Wissen zwischen Sessions
verloren. Jede neue Session fängt praktisch bei null an:
Architekturentscheidungen, Konventionen und der aktuelle Stand müssen
ständig neu erklärt werden. Das kostet Zeit und Tokens.

Dazu kommt der Teamfall. Drei Personen arbeiten am selben Repository,
jede in ihrer eigenen Claude-Code-Session, und keine Session weiß, was
die anderen gerade tun.

## Die Randbedingung, die alles bestimmt

Jede Person im Team hat eine normale Claude-Membership, keinen
Anthropic-API-Zugang mit eigener Abrechnung.

Claude Code kann sich über die Membership anmelden statt über einen
API-Schlüssel — das ist laut Nutzungsbedingungen aber ausdrücklich für
die individuelle Nutzung gedacht. Ein zentraler Dienst, der für mehrere
Personen gleichzeitig Anfragen an Claude verarbeitet, wäre keine
individuelle Nutzung mehr und bräuchte einen echten API-Schlüssel mit
Abrechnung.

**Daraus folgt: kein zentraler Server, der selbst KI-Logik ausführt.**
Jede Person nutzt weiter ihre eigene Session. Das Plugin verschiebt nur
Textdateien über git. Diese eine Randbedingung erklärt fast jede
Architekturentscheidung weiter unten.

## Vorbilder und Abgrenzung

**Xirp von Spotify** war der Ausgangspunkt: eine Entwicklungsumgebung mit
eingebautem Teamgedächtnis auf Basis von Spotify Portal. Das Konzept
dahinter — jede Coding-Session erzeugt Wissen über das System, das
automatisch zu Dokumentation wird und in künftige Sessions
zurückfließt, plus Sichtbarkeit darüber, wer woran gearbeitet hat.

Xirp ist allerdings für Organisationen mit Servicekatalog und verteilter
Ownership gebaut. Auf ein Dreierteam an einem Repo passt das nicht.

**claude-mem** ist ein bestehendes Open-Source-Werkzeug mit ähnlichem
Grundprinzip, aber generischer und mit eigenem
Hintergrund-Worker-Prozess.

Entscheidung: ein eigenes, schlankes Werkzeug für dieses eine Team und
dieses eine Repo, statt ein generisches zu übernehmen oder
nachzubauen.

## Die gewählte Architektur

Keine Verbindung zwischen laufenden Sessions, sondern ein gemeinsamer,
laufend aktualisierter Wissensstand im selben Git-Repository, auf einem
eigenen Branch `team-channel`, als git worktree neben dem Projektordner
ausgecheckt.

### Warum ein eigener Branch

Der Stand des Teams gehört zum Projekt, aber nicht in den Projektcode.
Ein eigener Branch hält beides sauber getrennt und braucht trotzdem
keine zusätzliche Infrastruktur: Das Remote steht schon, die
Zugriffsrechte auch, und wer das Repo klonen darf, darf auch den Channel
lesen.

Der Branch ist verwaist, hat also keinen gemeinsamen Vorfahren mit
`main`. Damit taucht er in keinem Vergleich und keinem
Merge-Vorschlag auf.

### Warum ein Worktree

Ein zweiter Ordner statt eines zweiten Klons: Beide teilen sich dasselbe
`.git`, kosten also keinen zusätzlichen Plattenplatz und keine zweite
Konfiguration. Und der Channel bleibt außerhalb des Projektordners, taucht
dort also nie als ungetrackte Änderung auf.

### Warum eine Datei pro Person, Frage und Entscheidung

Damit es praktisch nie Merge-Konflikte gibt. Drei Personen, die
gleichzeitig committen und pushen, fassen nie dieselbe Datei an.

Das ist auch der Grund, warum die Sperrdatei der Skripte im
Git-Verzeichnis liegt und nicht im Channel: Zwei Rechner mit je eigener
Sperrdatei im Arbeitsbaum hätten sich bei jedem Rebase genau darum
gestritten.

### Warum drei Hooks statt einem

- `SessionStart` liest. Er ist der eigentliche Zweck: der Stand des
  Teams landet ohne Zutun in der Session.
- `SessionEnd` schreibt beim echten Beenden.
- `Stop` schreibt gedrosselt zwischendurch. Ohne ihn stünde jemand mit
  einer den ganzen Tag offenen Session im Channel dauerhaft mit dem
  Stand von gestern. Für ein Werkzeug, das zeigen soll, wer gerade woran
  sitzt, wäre das der entscheidende Fehler.

Die Drosselung auf zehn Minuten ist der Kompromiss zwischen Aktualität
und einem Commit pro Nachricht.

### Warum keine KI-Zusammenfassung im Hintergrund

Der automatische Status wird aus dem Transkript zusammengesetzt, ohne
Modellaufruf: ursprünglicher Auftrag, letzte Anfrage, angefasste
Dateien.

Ein Hintergrundskript, das für jede Statuszeile ungefragt Kontingent
verbraucht, wäre ein schlechter Tausch — und zwar aus dem Kontingent
der Person, die gerade arbeitet. Nachrüstbar wäre es (der Hook könnte
`claude -p` aufrufen), aber erst, wenn sich zeigt, dass die einfache
Version nicht reicht.

`/sync` ist die Antwort darauf: Dort formuliert Claude die
Zusammenfassung im ohnehin laufenden Kontext, also ohne zusätzliche
Kosten, und mit dem vollen Wissen über die Session.

### Warum die Slash-Commands nur den Inhalt liefern

Der erste Entwurf beschrieb in jedem Command in acht Prosaschritten,
welche git-Befehle Claude ausführen soll. Das kostet bei jedem Aufruf
Tokens für Anweisungen, die sich nie ändern, und das Ergebnis hängt
davon ab, ob die Schritte diesmal genau befolgt wurden.

Dateiname, Kopffelder, Commit und Push sind aber immer gleich. Sie
gehören in `team_sync.py`. Für Claude bleibt, was ein Skript nicht kann:
den Inhalt formulieren.

## Nachtrag: vom Logbuch zum Abstimmen (0.3.0)

Die erste Fassung war ein Logbuch. Sie hielt fest, was passiert war, und
wurde einmal beim Sessionstart gelesen. Im Gespräch über den echten
Alltag kamen zwei Dinge heraus, die das nicht deckt.

**Die Sessions laufen oft autonom über Stunden.** Damit ist der
Empfänger einer Meldung nicht der Mensch vor dem Bildschirm, sondern
Claude selbst. Das ist kein Nachteil — Claude kann reagieren, ohne dass
jemand hinschaut. Aber es verschiebt, wofür das Werkzeug gebaut sein
muss: Meldungen sind Handlungsanweisungen, keine Rückfragen. Es ist
niemand da, der antworten könnte.

**Der Status beantwortet die falsche Frage.** Er meldet Vergangenes
("Max hat diese Dateien angefasst") und ist bis zu zehn Minuten alt. Als
Logbuch reicht das, als Kollisionsschutz ist es zu grob und zu spät.
Gebraucht wird eine **Reservierung**: "Ich bin an auth.py dran, seit
14:32."

### Der Satz, an dem das Design hängt

> Warten darf nie Blockieren heißen.

Eine autonome Session, die fünf Minuten wartet, verbrennt fünf Minuten —
genau die Zeit, die gewonnen werden soll. Deshalb: Anfrage ablegen,
sofort am nächsten Punkt weiterarbeiten, später zurückkommen. Aus totem
Warten wird ein Kontextwechsel.

Daraus folgt auch, warum der Hook vor einem Edit **nie blockiert**.
Verweigern wäre der sichere Weg gegen doppelte Arbeit — aber ein
Fehlalarm bremst eine autonome Session dann stundenlang, ohne dass es
jemand merkt. Ein Hinweis, den Claude ignorieren kann, ist das kleinere
Übel. Ob das reicht, zeigt erst der Alltag.

### Warum der Branch mitzählt

Zwei Sessions an derselben Datei bedeuten je nach Branch Verschiedenes.
Gleicher Branch heißt Merge-Chaos, verschiedene Branches löst git später
ohnehin. Ohne diese Unterscheidung wäre die Warnung ein
Fehlalarm-Generator — und nach dem dritten Fehlalarm wird sie überlesen.
Dann ist die Maschinerie gebaut und nichts gewonnen.

### Was offen bleibt

Dass drei Sessions dasselbe Problem auf drei Arten lösen und die
Codebase uneinheitlich wird, ist ein eigenes Problem. Dagegen hilft keine
Kollisionswarnung, sondern nur Festlegungen, die präsent bleiben — in
einer Vier-Stunden-Session ist der Startkontext längst aus dem Fenster
gerutscht. Der Rückkanal meldet neue Entscheidungen inzwischen mitten in
die laufende Arbeit; ob das genügt, muss sich zeigen.

---

## Nachtrag: ein zweites Hostprogramm (0.4.0)

Die erste Fassung setzte voraus, dass alle im Team Claude Code benutzen.
Das war nie eine Eigenschaft des Entwurfs, sondern eine Eigenschaft der
Hooks: Der Kanal ist ein Git-Branch mit Markdown darin, und dem ist
gleich, wer ihn beschreibt. Trotzdem stand in jedem Hook-Skript ein
Nutzlastformat und ein Antwortformat fest verdrahtet.

Die Annahme kippt bei der ersten Person, die mit etwas anderem arbeitet.
Genau das war der Anlass: eine Person mit Antigravity, zwei mit Claude
Code, ein Repository.

### Warum eine Abstraktion und kein zweites Plugin

Ein eigenständiges Antigravity-Plugin wäre schneller fertig gewesen und
hätte sich binnen Monaten auseinanderentwickelt. Zwei Fassungen desselben
Dateiformats, die sich langsam auseinanderbewegen, sind für einen
geteilten Kanal die schlimmste aller Varianten: Es funktioniert, bis es
still nicht mehr funktioniert.

Deshalb eine einzige Stelle, `lib/host.py`, die beide Protokolle
übersetzt, und darunter unveränderte Sachlogik. Ein Statuseintrag aus
Antigravity ist für Claude Code kein Sonderfall, sondern ein ganz
gewöhnlicher Statuseintrag.

### Warum die Dateiliste aus den eigenen Hooks kommt

Der automatische Status brauchte zwei Angaben, und beide kamen aus dem
Transkript. Dessen Format gehört aber dem Hostprogramm. Für Claude Code
ist es dokumentiert und stabil, anderswo nicht.

Die Liste der angefassten Dateien lässt sich ohne das Transkript
gewinnen, denn der Reservierungs-Hook sieht ohnehin jede Datei, sobald
sie angefasst wird. Damit hängt nur noch der Freitext an einem fremden
Format, und wenn der fehlt, ist der Status dünner statt falsch.

### Der Preis, den die Abstraktion nicht abfängt

Antigravity erwartet vor einem Werkzeugaufruf eine Antwort mit genau
einem Feld. Einen Hinweistext gibt es dort nicht, und ein zusätzliches
Feld kann der Parser ablehnen. Abgelehnte Hook-Antworten haben in
anderen Projekten dazu geführt, dass jeder Werkzeugaufruf verweigert
wurde, und das ist genau der Fehlermodus, den dieses Plugin um jeden
Preis vermeiden will.

Der Hinweis wird deshalb zurückgestellt und beim nächsten Modellaufruf
nachgereicht. Er kommt damit einen Schritt zu spät, also erst nach dem
ersten Edit. Gemessen an der Alternative, einer Sitzung, die bei jedem
Werkzeugaufruf abgewiesen wird, ist das kein schwerer Handel.

---

## Bewusste Grenzen

**Kein Echtzeit-Chat.** Zwei gleichzeitig laufende Sessions reden nicht
miteinander. Austausch passiert beim Sessionstart und bei jedem
Zwischenstand.

**Kein `contracts/` Ordner** für automatisch gepflegte
Schnittstellendokumentation. War in der Planung Schritt drei und ist
bewusst verschoben, bis sich der Rest im Alltag bewährt hat.

**Kein Erzwingen.** Die Hooks informieren, sie verhindern nichts. Dass
nicht zwei Leute dieselbe Datei umbauen, bleibt Teamsache. Das Werkzeug
macht nur wahrscheinlicher, dass es rechtzeitig auffällt.

## Rollout

1. Zu dritt mit `status/` und `questions/` mindestens eine Woche im
   echten Alltag testen.
2. Danach `decisions/` aktiv nutzen. Das zahlt sich erst nach einigen
   Wochen aus, wenn jemand eine alte Entscheidung nachschlägt.
3. `contracts/` als späterer Ausbauschritt, falls sich das Grundsystem
   bewährt.

Parallel dazu soll das Plugin **Superpowers**
(obra/superpowers-marketplace) im Team installiert werden, für TDD- und
Debugging-Skills. Es läuft ohne Konflikt neben team-sync.
