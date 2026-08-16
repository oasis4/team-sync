---
name: ask
description: Hinterlegt eine Frage an ein Teammitglied im Team-Channel
---

Der Nutzer möchte eine Frage für ein Teammitglied hinterlegen.

Argumente: $ARGUMENTS — das erste Wort ist die Zielperson, der Rest die Frage.

Deine Aufgabe ist der Inhalt, nicht die Mechanik. Dateiname, Kopffelder,
Commit und Push erledigt das Skript.

1. Formuliere die Frage so aus, dass sie ohne diese Session verständlich
   ist. Die Zielperson liest sie morgen in ihrer eigenen Session, ohne zu
   wissen, worüber hier gerade gesprochen wurde. Ergänze also knapp den
   nötigen Kontext: um welche Datei, welchen Branch, welches Problem es
   geht. Zwei bis fünf Sätze, keine Romane.
2. Wenn die Frage aus dem bisherigen Gespräch heraus unklar ist, frag
   beim Nutzer nach, statt etwas zu erfinden.
3. Rufe dann auf:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" ask --to <person> --titel "<kurztitel>" --text "<ausformulierte frage>"
   ```

   Enthält der Text Anführungszeichen, Zeilenumbrüche oder Sonderzeichen,
   schreib ihn stattdessen mit dem Write-Tool in eine temporäre Datei und
   übergib `--text-file <pfad>`. Das ist zuverlässiger als jedes Quoting.
4. Gib die Rückmeldung des Skripts knapp an den Nutzer weiter. Meldet es,
   dass der Push nicht geklappt hat, sag das ausdrücklich — die Frage
   liegt dann nur lokal und niemand sieht sie.
