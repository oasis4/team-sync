---
name: post
description: Schreibt eine kurze Nachricht an Teammitglieder in den Team-Channel, etwa eine Übergabe, eine geänderte Schnittstelle oder einen Blocker
---

Der Nutzer möchte Teammitgliedern etwas mitteilen. Die Nachricht landet
im Team-Channel und weckt die Sessions der Empfänger, auch wenn die
gerade auf Eingabe warten.

Argumente: $ARGUMENTS, der Inhalt, meist mit `@name` darin.

Wofür das gedacht ist: Übergaben („Login ist gemergt, @max kann die
API-Route bauen"), Änderungen, von denen andere abhängen („@alle
DB_URL heißt jetzt DATABASE_URL"), und Blocker („@lars ich brauche das
Schema für orders"). Eine Frage, auf die eine Antwort nötig ist, gehört
zu /ask, eine Festlegung zu /decide.

1. Formuliere kurz und für jemanden, der diese Session nicht kennt: was
   sich geändert hat, welche Dateien oder Schnittstellen betroffen sind
   und was du von wem brauchst. Zwei bis vier Sätze.
2. Adressiere mit `@name`. Der Vorname genügt, das Skript löst ihn auf.
   `@alle` nur, wenn es wirklich alle betrifft: Jede Nachricht weckt die
   Sessions ihrer Empfänger. Ohne `@name` geht sie an alle.
3. Schreib keine Nachricht, die nur bestätigt, dankt oder „ok" sagt.
4. Rufe auf:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_sync.py" post --text "@max <nachricht>"
   ```

   Enthält der Text Anführungszeichen oder Zeilenumbrüche, schreib ihn
   mit dem Write-Tool in eine temporäre Datei und übergib
   `--text-file <pfad>`.
5. Gib die Rückmeldung knapp weiter. Meldet das Skript einen
   mehrdeutigen oder unbekannten Namen, sag das dem Nutzer und frag, wer
   gemeint ist. Meldet es, dass der Push nicht geklappt hat, sag das
   ausdrücklich, dann liegt die Nachricht nur lokal.
