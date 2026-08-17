---
name: team
description: Zeigt, wer gerade woran arbeitet und was offen ist
---

Der Nutzer möchte den aktuellen Stand des Teams sehen.

1. Hol die Übersicht:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" uebersicht
   ```

2. Gib sie kompakt wieder und ergänze, was auffällt, statt sie nur
   abzuschreiben:
   - Arbeitet jemand auf demselben Branch oder an denselben Dateien wie
     der Nutzer gerade? Dann sag es deutlich, das ist der wichtigste
     Punkt der ganzen Ausgabe.
   - Unter „Aktuell belegte Dateien" steht, wer in diesem Moment woran
     sitzt. Das ist genauer als der Status, weil es beim Zugriff
     entsteht und nicht alle zehn Minuten. Betrifft eine davon das, was
     als Nächstes ansteht, sag es, bevor ihr anfangt.
   - Sind Fragen an den Nutzer offen? Weise darauf hin, dass /answer sie
     beantwortet.
   - Ist ein Status als veraltet markiert, nimm ihn nicht für bare Münze.
     Die Person hat seit über zwei Tagen nichts geschrieben, sie kann
     längst woanders sein.
3. Meldet das Skript, dass kein Channel eingerichtet ist, erklär kurz das
   einmalige Setup statt die Meldung nur weiterzureichen.

Dieser Command liest nur und ändert nichts.
