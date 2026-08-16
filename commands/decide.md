---
name: decide
description: Protokolliert eine Architekturentscheidung mit Begründung und verworfenen Alternativen
---

Der Nutzer möchte eine Entscheidung im Team-Channel festhalten.

Argumente: $ARGUMENTS — eine kurze Beschreibung der Entscheidung.

Der Wert eines Entscheidungsprotokolls liegt nicht im Was, sondern im
Warum. Dass auf JWT umgestellt wurde, sieht man im Code. Warum
Server-Sessions verworfen wurden, weiß in drei Monaten niemand mehr.
Achte darauf, dass die Begründung und die Alternativen wirklich
dastehen.

1. Zieh aus dem bisherigen Gesprächsverlauf zusammen:
   - Worum ging es (das Problem, nicht die Lösung)
   - Was wurde entschieden
   - Warum, mit dem Argument, das den Ausschlag gab
   - Welche Alternativen wurden erwogen und woran sind sie gescheitert
2. Fehlt einer dieser Punkte im Gespräch, frag den Nutzer danach. Rate
   nichts hinein, besonders nicht bei den Alternativen. Eine erfundene
   Begründung ist schlimmer als eine fehlende, weil sie später geglaubt
   wird.
3. Wurde die Entscheidung im Gespräch nur angedeutet und nicht wirklich
   getroffen, sag das und frag nach, statt sie festzuschreiben.
4. Trag sie ein:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" decide \
     --titel "<kurz und suchbar>" \
     --kontext "<worum ging es>" \
     --entscheidung "<was gilt jetzt>" \
     --begruendung "<warum>" \
     --alternative "<verworfene Option: warum verworfen>" \
     --alternative "<weitere, falls vorhanden>" \
     --betrifft "<datei oder komponente>"
   ```

   `--alternative` und `--betrifft` können mehrfach vorkommen, `--kontext`,
   `--begruendung`, `--alternative` und `--betrifft` sind optional.
5. Bestätige knapp und nenne den Dateinamen.
