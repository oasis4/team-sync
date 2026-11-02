---
description: Schreibt eine kurze Nachricht an Teammitglieder in den Team-Channel, etwa eine Übergabe oder eine geänderte Schnittstelle
---

Der Nutzer möchte Teammitgliedern etwas mitteilen. Die Nachricht landet
im Team-Channel und erreicht die Sitzungen der Empfänger.

Wofür das gedacht ist: Übergaben („Login ist gemergt, @max kann die
API-Route bauen"), Änderungen, von denen andere abhängen („@alle
DB_URL heißt jetzt DATABASE_URL"), und Blocker. Eine Frage, auf die
eine Antwort nötig ist, gehört zu /ask, eine Festlegung zu /decide.

1. Formuliere kurz und für jemanden, der diese Sitzung nicht kennt: was
   sich geändert hat, welche Dateien oder Schnittstellen betroffen sind
   und was du von wem brauchst. Zwei bis vier Sätze.
2. Adressiere mit `@name`. Der Vorname genügt. `@alle` nur, wenn es
   wirklich alle betrifft. Ohne `@name` geht die Nachricht an alle.
3. Schreib keine Nachricht, die nur bestätigt oder dankt.
4. Rufe auf:

   ```
   python3 "{{TEAM_SYNC_ROOT}}/scripts/team_sync.py" post --text "@max <nachricht>"
   ```

   Enthält der Text Anführungszeichen oder Zeilenumbrüche, schreib ihn
   in eine temporäre Datei und übergib `--text-file <pfad>`.
5. Gib die Rückmeldung knapp weiter. Bei einem mehrdeutigen oder
   unbekannten Namen frag den Nutzer, wer gemeint ist. Hat der Push
   nicht geklappt, sag das ausdrücklich.
