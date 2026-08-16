"""
Integrationstests: zwei Teammitglieder, ein Remote, echte git-Aufrufe.
"""

import json
import unittest

from helpers import TeamTestCase, git, nutzer_nachricht, werkzeug_aufruf


class TestSetup(TeamTestCase):
    def test_erste_person_legt_channel_an(self):
        ergebnis = self.team.setup("Lars")
        self.assertErfolg(ergebnis, "Setup fehlgeschlagen")

        channel = self.team.channels["Lars"]
        self.assertTrue(channel.is_dir())
        for unterordner in ("status", "questions", "decisions"):
            self.assertTrue((channel / unterordner).is_dir(), unterordner)
        self.assertTrue((channel / "README.md").is_file())

    def test_channel_branch_ist_verwaist(self):
        """
        Der Channel darf keinen gemeinsamen Vorfahren mit main haben.
        Sonst taucht er in Vergleichen und Merge-Vorschlägen auf, und
        irgendwann landen Notizen versehentlich im Projektverlauf.
        """
        self.team.setup("Lars")
        projekt = self.team.projekte["Lars"]

        ergebnis = git(
            ["merge-base", "main", "team-channel"], cwd=projekt, check=False
        )
        self.assertNotEqual(
            ergebnis.returncode, 0,
            "team-channel teilt Historie mit main, ist also nicht verwaist",
        )

    def test_zweite_person_uebernimmt_bestehenden_channel(self):
        self.team.setup("Lars")
        ergebnis = self.team.setup("Max")
        self.assertErfolg(ergebnis, "Zweites Setup fehlgeschlagen")

        # Beide müssen denselben Startcommit sehen.
        lars = git(["rev-parse", "team-channel"], cwd=self.team.projekte["Lars"])
        max_ = git(["rev-parse", "team-channel"], cwd=self.team.projekte["Max"])
        self.assertEqual(lars.stdout.strip(), max_.stdout.strip())

    def test_setup_ist_wiederholbar(self):
        self.team.setup("Lars")
        zweiter_lauf = self.team.setup("Lars")
        self.assertErfolg(zweiter_lauf)
        self.assertIn("bereits eingerichtet", zweiter_lauf.stdout)

    def test_ohne_git_repo_klare_fehlermeldung(self):
        leer = self.basis / "kein-repo"
        leer.mkdir()
        import subprocess
        import sys

        from helpers import SCRIPTS

        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / "setup_channel.py")],
            cwd=str(leer), capture_output=True, text=True,
        )
        self.assertNotEqual(ergebnis.returncode, 0)
        self.assertIn("kein Git-Repository", ergebnis.stderr)


class TestFragen(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.setup_alle()

    def test_frage_erreicht_die_andere_person(self):
        gestellt = self.team.cli(
            "Lars", "ask", "--to", "Max",
            "--titel", "Session-Verwaltung",
            "--text", "Wie hast du die Session-Verwaltung im Frontend gelöst?",
        )
        self.assertErfolg(gestellt, "ask fehlgeschlagen")

        offen = self.team.cli("Max", "fragen", "--json")
        self.assertErfolg(offen)
        fragen = json.loads(offen.stdout)
        self.assertEqual(len(fragen), 1)
        self.assertEqual(fragen[0]["von"], "lars")
        self.assertEqual(fragen[0]["an"], "max")
        self.assertIn("Session-Verwaltung", fragen[0]["text"])

    def test_frage_an_andere_taucht_bei_mir_nicht_auf(self):
        self.team.cli("Lars", "ask", "--to", "Max", "--text", "Frage an Max")

        eigene = self.team.cli("Lars", "fragen", "--json")
        self.assertEqual(json.loads(eigene.stdout), [])

    def test_umlaute_im_namen(self):
        """
        Ein Name mit Umlaut muss auf beiden Seiten denselben Slug
        ergeben, sonst kommt die Frage nie an.
        """
        self.team.person_anlegen("Jörg", ordner="joerg")
        self.assertErfolg(self.team.setup("Jörg"))

        self.assertErfolg(
            self.team.cli("Lars", "ask", "--to", "Jörg", "--text", "Frage für Jörg")
        )
        offen = self.team.cli("Jörg", "fragen", "--json")
        self.assertErfolg(offen)
        self.assertEqual(len(json.loads(offen.stdout)), 1)

    def test_antwort_landet_beim_fragesteller(self):
        self.team.cli("Lars", "ask", "--to", "Max", "--titel", "Auth", "--text", "Wie?")

        offen = json.loads(self.team.cli("Max", "fragen", "--json").stdout)
        frage_id = offen[0]["id"]

        geantwortet = self.team.cli(
            "Max", "answer", "--id", frage_id, "--text", "Über einen JWT im Header."
        )
        self.assertErfolg(geantwortet, "answer fehlgeschlagen")

        # Bei Max ist nichts mehr offen.
        self.assertEqual(json.loads(self.team.cli("Max", "fragen", "--json").stdout), [])

        # Lars sieht die Antwort nach einem Pull.
        self.team.cli("Lars", "uebersicht")
        datei = self.team.channel_datei("Lars", f"questions/{frage_id}.md")
        inhalt = datei.read_text(encoding="utf-8")
        self.assertIn("JWT im Header", inhalt)
        self.assertIn("status: beantwortet", inhalt)

    def test_antwort_auf_unbekannte_frage(self):
        ergebnis = self.team.cli("Max", "answer", "--id", "gibt-es-nicht", "--text", "x")
        self.assertEqual(ergebnis.returncode, 1)
        self.assertIn("Keine Frage", ergebnis.stderr)

    def test_doppelte_antwort_wird_erkannt(self):
        self.team.cli("Lars", "ask", "--to", "Max", "--text", "Frage")
        frage_id = json.loads(self.team.cli("Max", "fragen", "--json").stdout)[0]["id"]

        self.team.cli("Max", "answer", "--id", frage_id, "--text", "Erste Antwort")
        zweiter = self.team.cli("Max", "answer", "--id", frage_id, "--text", "Zweite")
        self.assertErfolg(zweiter)
        self.assertIn("bereits beantwortet", zweiter.stdout)

        inhalt = self.team.channel_datei("Max", f"questions/{frage_id}.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Zweite", inhalt)

    def test_leere_frage_wird_abgelehnt(self):
        ergebnis = self.team.cli("Lars", "ask", "--to", "Max", "--text", "   ")
        self.assertEqual(ergebnis.returncode, 1)

    def test_text_ueber_standardeingabe(self):
        ergebnis = self.team.cli(
            "Lars", "ask", "--to", "Max", "--text", "-",
            stdin="Mehrzeilige Frage\nmit \"Anführungszeichen\" und Umlauten: äöü",
        )
        self.assertErfolg(ergebnis)
        fragen = json.loads(self.team.cli("Max", "fragen", "--json").stdout)
        self.assertIn("äöü", fragen[0]["text"])


class TestEntscheidungen(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.setup_alle()

    def test_entscheidung_wird_protokolliert(self):
        ergebnis = self.team.cli(
            "Lars", "decide",
            "--titel", "JWT statt Server-Session",
            "--kontext", "Die Anmeldung brauchte eine Entscheidung.",
            "--entscheidung", "Wir nutzen JWT im Authorization-Header.",
            "--begruendung", "Kein geteilter Sitzungsspeicher nötig.",
            "--alternative", "Server-Sessions: braucht Redis, zu viel Betrieb.",
            "--betrifft", "auth/",
        )
        self.assertErfolg(ergebnis, "decide fehlgeschlagen")

        dateien = list((self.team.channels["Lars"] / "decisions").glob("*.md"))
        self.assertEqual(len(dateien), 1)
        inhalt = dateien[0].read_text(encoding="utf-8")
        self.assertIn("JWT statt Server-Session", inhalt)
        self.assertIn("Kein geteilter Sitzungsspeicher", inhalt)
        self.assertIn("Server-Sessions", inhalt)
        self.assertIn("auth/", inhalt)

    def test_entscheidung_erscheint_bei_der_anderen_person(self):
        self.team.cli(
            "Lars", "decide", "--titel", "Postgres statt SQLite",
            "--entscheidung", "Wir setzen auf Postgres.",
        )
        kontext = self.team.cli("Max", "kontext")
        self.assertErfolg(kontext)
        self.assertIn("Postgres statt SQLite", kontext.stdout)
        self.assertIn("Wir setzen auf Postgres", kontext.stdout)


class TestStatus(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.setup_alle()

    def test_sync_schreibt_status(self):
        ergebnis = self.team.cli(
            "Lars", "sync",
            "--text", "Anmeldung umgebaut, Tests fehlen noch.",
            "--datei", "auth.py",
        )
        self.assertErfolg(ergebnis, "sync fehlgeschlagen")

        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("quelle: manuell", inhalt)
        self.assertIn("Anmeldung umgebaut", inhalt)
        self.assertIn("auth.py", inhalt)

    def test_anderer_sieht_den_status_im_kontext(self):
        self.team.cli("Lars", "sync", "--text", "Ich baue gerade die Anmeldung um.")

        kontext = self.team.cli("Max", "kontext")
        self.assertErfolg(kontext)
        self.assertIn("lars", kontext.stdout)
        self.assertIn("Anmeldung", kontext.stdout)

    def test_eigener_status_steht_nicht_im_eigenen_kontext(self):
        """Der eigene Stand ist keine neue Information und kostet nur Tokens."""
        self.team.cli("Lars", "sync", "--text", "Meine eigene Notiz")

        kontext = self.team.cli("Lars", "kontext")
        self.assertNotIn("Meine eigene Notiz", kontext.stdout)

    def test_branch_wird_mitgeschrieben(self):
        projekt = self.team.projekte["Lars"]
        git(["checkout", "-b", "feature/anmeldung"], cwd=projekt)

        self.team.cli("Lars", "sync", "--text", "Arbeit am Feature-Branch")
        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("branch: feature/anmeldung", inhalt)


class TestHooks(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.setup_alle()

    def test_sessionstart_liefert_gueltiges_hook_json(self):
        """
        Der erste Entwurf gab {"additionalContext": ...} auf oberster
        Ebene aus. Claude Code erwartet das Feld unter
        hookSpecificOutput, der Kontext wäre also nie angekommen.
        """
        self.team.cli("Lars", "sync", "--text", "Woran ich sitze")

        ergebnis = self.team.hook(
            "Max", "session_start.py",
            {"hook_event_name": "SessionStart", "session_id": "test"},
        )
        self.assertErfolg(ergebnis, "SessionStart-Hook fehlgeschlagen")

        daten = json.loads(ergebnis.stdout)
        self.assertIn("hookSpecificOutput", daten)
        self.assertEqual(
            daten["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        self.assertIn("Woran ich sitze", daten["hookSpecificOutput"]["additionalContext"])

    def test_sessionstart_ohne_channel_bleibt_still(self):
        self.team.person_anlegen("Ohne", ordner="ohne")
        ergebnis = self.team.hook("Ohne", "session_start.py", {})
        self.assertErfolg(ergebnis)
        self.assertEqual(ergebnis.stdout.strip(), "")

    def test_sessionstart_bei_leerem_channel(self):
        ergebnis = self.team.hook("Lars", "session_start.py", {})
        self.assertErfolg(ergebnis)
        self.assertEqual(ergebnis.stdout.strip(), "")

    def test_sessionende_schreibt_status_aus_transkript(self):
        transkript = self.team.transkript_schreiben("Lars", [
            nutzer_nachricht("Bau bitte die Zahlungsabwicklung ein"),
            werkzeug_aufruf("Edit", str(self.team.projekte["Lars"] / "zahlung.py")),
            werkzeug_aufruf("Write", str(self.team.projekte["Lars"] / "test_zahlung.py")),
        ])

        ergebnis = self.team.hook(
            "Lars", "session_end.py",
            {"transcript_path": str(transkript), "session_end_reason": "logout"},
        )
        self.assertErfolg(ergebnis, "SessionEnd-Hook fehlgeschlagen")

        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Zahlungsabwicklung", inhalt)
        self.assertIn("zahlung.py", inhalt)
        self.assertIn("quelle: sessionende", inhalt)

    def test_dateipfade_werden_projektrelativ(self):
        """Absolute Pfade vom Rechner eines anderen helfen niemandem."""
        transkript = self.team.transkript_schreiben("Lars", [
            nutzer_nachricht("Auftrag"),
            werkzeug_aufruf("Edit", str(self.team.projekte["Lars"] / "src" / "app.py")),
        ])
        self.team.hook("Lars", "session_end.py", {"transcript_path": str(transkript)})

        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("app.py", inhalt)
        self.assertNotIn(str(self.team.basis), inhalt)

    def test_zwischenstand_ist_gedrosselt(self):
        transkript = self.team.transkript_schreiben("Lars", [
            nutzer_nachricht("Erster Auftrag"),
        ])
        erster = self.team.hook(
            "Lars", "session_checkpoint.py", {"transcript_path": str(transkript)}
        )
        self.assertErfolg(erster)
        self.assertTrue(self.team.channel_datei("Lars", "status/lars.md").is_file())

        # Sofort danach: darf nichts schreiben.
        zweites_transkript = self.team.transkript_schreiben("Lars", [
            nutzer_nachricht("Zweiter Auftrag, darf noch nicht erscheinen"),
        ])
        self.team.hook(
            "Lars", "session_checkpoint.py",
            {"transcript_path": str(zweites_transkript)},
        )
        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Erster Auftrag", inhalt)
        self.assertNotIn("Zweiter Auftrag", inhalt)

    def test_zwischenstand_nach_ablauf_der_drosselung(self):
        transkript = self.team.transkript_schreiben("Lars", [nutzer_nachricht("Erster")])
        self.team.hook("Lars", "session_checkpoint.py", {"transcript_path": str(transkript)})

        neues = self.team.transkript_schreiben("Lars", [nutzer_nachricht("Zweiter Auftrag")])
        self.team.hook(
            "Lars", "session_checkpoint.py",
            {"transcript_path": str(neues)},
            extra={"TEAM_SYNC_CHECKPOINT_SECONDS": "0"},
        )
        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Zweiter Auftrag", inhalt)

    def test_sync_setzt_die_drosselung_zurueck(self):
        """
        Sonst überschreibt der automatische Zwischenstand kurz darauf
        die von Claude formulierte Zusammenfassung wieder mit der groben
        Heuristik, und /sync wäre wirkungslos.
        """
        self.team.cli("Lars", "sync", "--text", "Sorgfältig formulierter Stand")

        transkript = self.team.transkript_schreiben("Lars", [
            nutzer_nachricht("grobe letzte Nachricht"),
        ])
        self.team.hook(
            "Lars", "session_checkpoint.py", {"transcript_path": str(transkript)}
        )

        inhalt = self.team.channel_datei("Lars", "status/lars.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Sorgfältig formulierter Stand", inhalt)

    def test_hooks_ueberstehen_kaputte_eingaben(self):
        for skript in ("session_start.py", "session_checkpoint.py", "session_end.py"):
            for payload in ({"transcript_path": "/gibt/es/nicht"}, {}):
                ergebnis = self.team.hook("Lars", skript, payload)
                self.assertEqual(
                    ergebnis.returncode, 0,
                    f"{skript} ist bei {payload} ausgestiegen: {ergebnis.stderr}",
                )


class TestNebenlaeufigkeit(TeamTestCase):
    def setUp(self):
        super().setUp()
        self.setup_alle()

    def test_gleichzeitige_pushs_gehen_nicht_verloren(self):
        """
        Der Kernfall: Zwei Personen schreiben, ohne voneinander zu
        wissen. Wer als Zweiter pusht, wird abgewiesen und muss rebasen.
        Der erste Entwurf hat den abgelehnten Push verschluckt, der
        Status blieb dann still liegen.
        """
        # Beide holen denselben Stand.
        self.team.cli("Lars", "uebersicht")
        self.team.cli("Max", "uebersicht")

        # Max ist schneller.
        self.assertErfolg(self.team.cli("Max", "sync", "--text", "Max arbeitet an B"))
        # Lars pusht auf einen inzwischen veränderten Branch.
        self.assertErfolg(self.team.cli("Lars", "sync", "--text", "Lars arbeitet an A"))

        # Beide Stände müssen beim Remote liegen.
        self.team.cli("Max", "uebersicht")
        channel = self.team.channels["Max"]
        self.assertIn(
            "Lars arbeitet an A",
            (channel / "status" / "lars.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Max arbeitet an B",
            (channel / "status" / "max.md").read_text(encoding="utf-8"),
        )

    def test_fragen_von_beiden_seiten_kollidieren_nicht(self):
        self.team.cli("Lars", "ask", "--to", "Max", "--text", "Frage von Lars")
        self.team.cli("Max", "ask", "--to", "Lars", "--text", "Frage von Max")

        self.team.cli("Lars", "uebersicht")
        dateien = list((self.team.channels["Lars"] / "questions").glob("*.md"))
        self.assertEqual(len(dateien), 2, [d.name for d in dateien])


class TestDoctor(TeamTestCase):
    def test_meldet_fehlendes_setup(self):
        ergebnis = self.team.cli("Lars", "doctor")
        self.assertEqual(ergebnis.returncode, 1)
        self.assertIn("nicht eingerichtet", ergebnis.stdout)

    def test_meldet_vollstaendige_einrichtung(self):
        self.setup_alle()
        ergebnis = self.team.cli("Lars", "doctor")
        self.assertErfolg(ergebnis, f"doctor meldet Probleme:\n{ergebnis.stdout}")
        self.assertIn("Alles in Ordnung", ergebnis.stdout)


class TestOhneSetup(TeamTestCase):
    def test_kommandos_weisen_auf_das_setup_hin(self):
        for argumente in (
            ("ask", "--to", "Max", "--text", "x"),
            ("fragen",),
            ("uebersicht",),
            ("sync", "--text", "x"),
            ("decide", "--titel", "t", "--entscheidung", "e"),
        ):
            ergebnis = self.team.cli("Lars", *argumente)
            self.assertEqual(
                ergebnis.returncode, 2,
                f"{argumente[0]} sollte auf fehlendes Setup hinweisen",
            )
            self.assertIn("setup_channel.py", ergebnis.stdout)


if __name__ == "__main__":
    unittest.main()
