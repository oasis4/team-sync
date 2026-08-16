---
name: answer
description: Zeigt offene Fragen aus dem Team-Channel und trägt Antworten ein
---

Der Nutzer möchte offene, an ihn gerichtete Fragen beantworten.

1. Hole die offenen Fragen:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" fragen
   ```

   Kommt „keine" zurück, sag das in einem Satz und höre auf.
2. Nimm die Fragen der Reihe nach. Zu jeder:
   - Zeig sie dem Nutzer kurz an, mit Absender und Alter.
   - Sieh im Projekt nach, ob du die Antwort selbst belegen kannst. Genau
     dafür ist der Kanal da: Du hast dieses Repo vor dir, die fragende
     Person hatte es beim Fragen vielleicht nicht. Lies den betreffenden
     Code, statt aus dem Gedächtnis zu antworten.
   - Schlage eine Antwort vor und nenne dabei, worauf sie sich stützt
     (Datei, Zeile, Commit). Weißt du es nicht, sag das und frag den
     Nutzer.
   - Lass dir die Antwort bestätigen, bevor du sie einträgst. Sie geht an
     jemand anderen, und ein falscher Eintrag hält länger als ein
     falscher Satz im Chat.
3. Trage die bestätigte Antwort ein, direkt nach der Bestätigung, nicht
   gesammelt am Ende:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" answer --id <id> --text "<antwort>"
   ```

   Die `id` steht in der Auflistung. Für längere Antworten `--text-file`
   benutzen.
4. Nach allen Fragen: eine Zeile Zusammenfassung, was beantwortet wurde.
