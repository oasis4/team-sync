# Echte Simulation mit zwei Claude-Code-Sitzungen

`tests/szenario.py` prüft den Ablauf mit festen Entscheidungen. Diese
Skripte hier lassen dagegen zwei echte, interaktive Claude-Code-Sitzungen
gleichzeitig an einem kleinen Shop arbeiten, jede mit dem Plugin. Lars
stellt im Backend den Betrag auf Cent um, Max baut das Frontend und hängt
von Lars' Format ab. Beide müssen dafür an `shared/models.py`. Wie sie
sich abstimmen, wird ihnen nicht gesagt, das muss vom Plugin kommen.

Gedacht für eine abgeschottete Maschine, etwa eine Railway-Sandbox, nicht
für den eigenen Rechner. Die Sitzungen laufen ohne Rückfragen, dürfen in
der Shell aber nur git und die team-sync-Kommandozeile benutzen und
Dateien nur im Testprojekt bearbeiten.

```bash
simulation/aufbau.sh /tmp/sim "$PWD"
python3 simulation/lauf.py /tmp/sim "$PWD" sonnet 900
python3 simulation/auswertung.py /tmp/sim
```

Die Anmeldung bei Anthropic kommt aus `CLAUDE_CODE_OAUTH_TOKEN` oder
`ANTHROPIC_API_KEY`. Fehlen beide, wird die lokale Anmeldedatei für die
Dauer des Laufs kopiert und danach gelöscht.

`auswertung.py` baut aus dem Channel, dem Code-Verlauf und den
Transkripten beider Sitzungen eine Zeitleiste. Darin steht, wann welche
Meldung ankam und was Claude daraufhin getan hat.
