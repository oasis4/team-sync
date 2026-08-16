---
name: sync
description: Schreibt sofort einen selbst formulierten Status in den Team-Channel
---

Der Nutzer möchte seinen Status jetzt aktualisieren, ohne auf den
automatischen Zehn-Minuten-Takt zu warten. Typischer Anlass: Ein
größerer Schritt ist fertig und die anderen sollen es wissen, bevor sie
an derselben Stelle anfangen.

Der Unterschied zum automatischen Zwischenstand ist der Grund für diesen
Command: Das Hintergrundskript kennt nur die letzte Nutzernachricht und
die Liste angefasster Dateien. Du kennst den ganzen Gesprächsverlauf.
Schreib also, was ein Teammitglied wirklich wissen muss.

1. Fasse in drei bis sechs Sätzen zusammen:
   - Woran in dieser Session gearbeitet wurde und was davon fertig ist
   - Was gerade offen oder halbfertig ist, also wo jemand aufpassen muss
   - Was als Nächstes ansteht, falls das absehbar ist
   Schreib es für jemanden, der den Code kennt, aber diese Session nicht
   gesehen hat. Keine Aufzählung von Werkzeugaufrufen.
2. Melde halbfertige Stände ausdrücklich. Ein Status, der „fertig"
   suggeriert, wo etwas noch nicht läuft, ist schlimmer als kein Status,
   weil jemand darauf aufbaut.
3. Schreib ihn:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" sync --text "<zusammenfassung>"
   ```

   Für die Liste der angefassten Dateien kannst du `--datei <pfad>`
   mehrfach anhängen. Mehrzeilige Texte über `--text-file`.
4. Bestätige in einem Satz. Das Skript setzt die Drosselung selbst
   zurück, damit der nächste automatische Zwischenstand deine
   Zusammenfassung nicht gleich wieder überschreibt.
