"""
Die Host-Abstraktion und das Zusammenspiel zweier Programme.

Der Kern dieses Plugins ist, dass mehrere Personen am selben Repository
voneinander wissen. Ob eine davon Claude Code benutzt und die nächste
Antigravity, darf dafür keine Rolle spielen. Genau das wird hier
geprüft, und zwar an beiden Enden: dass die Nutzlast beider Programme
richtig gelesen wird, dass jedes die Antwort in seinem eigenen Format
bekommt, und dass eine Reservierung aus dem einen Programm im anderen
ankommt.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from helpers import (  # noqa: E402
    TeamTestCase,
    ag_nutzer_nachricht,
    ag_planer_antwort,
    git,
)
from lib import host  # noqa: E402


CC_PAYLOAD = {
    "session_id": "sess-1",
    "transcript_path": "/tmp/t.jsonl",
    "tool_name": "Edit",
    "permission_mode": "auto",
    "cwd": "/projekt",
    "tool_input": {"file_path": "/projekt/src/auth.py"},
}

AG_PAYLOAD = {
    "conversationId": "conv-1",
    "workspacePaths": ["/projekt"],
    "transcriptPath": "/tmp/t.json",
    "stepIdx": 4,
    "toolCall": {"name": "write_to_file", "args": {"TargetFile": "/projekt/src/auth.py"}},
}


class TestErkennung(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("TEAM_SYNC_HOST", None)

    def tearDown(self):
        os.environ.pop("TEAM_SYNC_HOST", None)
        if self._alt is not None:
            os.environ["TEAM_SYNC_HOST"] = self._alt

    def test_claude_wird_erkannt(self):
        self.assertEqual(host.erkenne_host(CC_PAYLOAD), host.CLAUDE)

    def test_antigravity_wird_erkannt(self):
        self.assertEqual(host.erkenne_host(AG_PAYLOAD), host.ANTIGRAVITY)

    def test_umgebungsvariable_schlaegt_die_nutzlast(self):
        os.environ["TEAM_SYNC_HOST"] = "antigravity"
        self.assertEqual(host.erkenne_host(CC_PAYLOAD), host.ANTIGRAVITY)

    def test_leere_nutzlast_faellt_auf_claude_zurueck(self):
        """
        Die alte Seite ist die sichere Vorgabe. Antigravity setzt in
        seinem eigenen Einstiegspunkt ohnehin TEAM_SYNC_HOST.
        """
        self.assertEqual(host.erkenne_host({}), host.CLAUDE)


class TestNutzlast(unittest.TestCase):
    def test_claude_felder(self):
        daten = host.Ereignis(host.CLAUDE, CC_PAYLOAD)
        self.assertEqual(daten.session, "sess-1")
        self.assertEqual(daten.transcript, "/tmp/t.jsonl")
        self.assertEqual(daten.werkzeug, "Edit")
        self.assertEqual(daten.datei, "/projekt/src/auth.py")
        self.assertEqual(daten.modus, "auto")
        self.assertTrue(daten.ist_edit())

    def test_antigravity_felder(self):
        daten = host.Ereignis(host.ANTIGRAVITY, AG_PAYLOAD)
        self.assertEqual(daten.session, "conv-1")
        self.assertEqual(daten.transcript, "/tmp/t.json")
        self.assertEqual(daten.werkzeug, "write_to_file")
        self.assertEqual(daten.datei, "/projekt/src/auth.py")
        self.assertEqual(daten.projekt, "/projekt")
        self.assertTrue(daten.ist_edit())

    def test_pfad_in_verschachtelten_argumenten(self):
        """
        Der Aufbau eines Werkzeugaufrufs liegt bei Antigravity nicht
        fest. Gesucht wird deshalb nach bekannten Schlüsselnamen, egal
        wie tief sie stecken.
        """
        payload = {
            "conversationId": "c",
            "toolCall": {
                "name": "replace_file_content",
                "arguments": {"target": {"absolutePath": "/projekt/a.py"}},
            },
        }
        self.assertEqual(host.Ereignis(host.ANTIGRAVITY, payload).datei, "/projekt/a.py")

    def test_argumente_als_zeichenkette(self):
        """Manche Hosts reichen die Argumente als JSON-Text durch."""
        payload = {
            "conversationId": "c",
            "toolCall": {"name": "edit_file", "args": json.dumps({"file_path": "/p/b.py"})},
        }
        self.assertEqual(host.Ereignis(host.ANTIGRAVITY, payload).datei, "/p/b.py")

    def test_dateiprotokoll_wird_abgeschnitten(self):
        payload = {
            "conversationId": "c",
            "toolCall": {"name": "write", "args": {"uri": "file:///projekt/c.py"}},
        }
        self.assertEqual(host.Ereignis(host.ANTIGRAVITY, payload).datei, "/projekt/c.py")

    def test_url_ist_kein_dateipfad(self):
        payload = {
            "conversationId": "c",
            "toolCall": {"name": "write", "args": {"uri": "https://example.test/x.py"}},
        }
        self.assertEqual(host.Ereignis(host.ANTIGRAVITY, payload).datei, "")

    def test_fehlende_felder_ergeben_leere_werte(self):
        """Ein Hook darf an einer unbekannten Nutzlast nicht scheitern."""
        for host_name in (host.CLAUDE, host.ANTIGRAVITY):
            daten = host.Ereignis(host_name, {})
            self.assertEqual(daten.datei, "")
            self.assertEqual(daten.session, "")
            self.assertFalse(daten.ist_edit())


class TestEditErkennung(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("TEAM_SYNC_AG_EDIT_TOOLS", None)

    def tearDown(self):
        os.environ.pop("TEAM_SYNC_AG_EDIT_TOOLS", None)
        if self._alt is not None:
            os.environ["TEAM_SYNC_AG_EDIT_TOOLS"] = self._alt

    def _ereignis(self, werkzeug, datei="/projekt/a.py"):
        return host.Ereignis(
            host.ANTIGRAVITY,
            {"toolCall": {"name": werkzeug, "args": {"file_path": datei}}},
        )

    def test_schreibende_namen_zaehlen(self):
        for name in ("write_to_file", "edit_file", "replace_file_content", "create_file"):
            self.assertTrue(self._ereignis(name).ist_edit(), name)

    def test_lesende_namen_zaehlen_nicht(self):
        for name in ("read_file", "view_file", "grep_search", "run_command"):
            self.assertFalse(self._ereignis(name).ist_edit(), name)

    def test_ohne_dateipfad_kein_edit(self):
        """
        Ein Werkzeug ohne Datei kann keine Reservierung auslösen, auch
        wenn sein Name schreibend klingt.
        """
        self.assertFalse(self._ereignis("write_memory", datei="").ist_edit())

    def test_eigene_liste_schlaegt_die_heuristik(self):
        os.environ["TEAM_SYNC_AG_EDIT_TOOLS"] = "apply_diff,mein_werkzeug"
        self.assertTrue(self._ereignis("mein_werkzeug").ist_edit())
        # Nicht in der Liste, also nicht relevant, auch wenn der Name passt.
        self.assertFalse(self._ereignis("write_to_file").ist_edit())

    def test_claude_bleibt_bei_der_festen_liste(self):
        daten = host.Ereignis(host.CLAUDE, {"tool_name": "Bash", "tool_input": {}})
        self.assertFalse(daten.ist_edit())


class TestAusgabeformat(unittest.TestCase):
    """
    Das Antwortformat ist der Punkt, an dem ein Hook still scheitert.

    Schickt man Antigravity die Claude-Code-Antwort, kann sein Parser
    sie ablehnen, und im schlimmsten Fall wird jeder Werkzeugaufruf
    verweigert. Deshalb hier für beide Seiten festgenagelt.
    """

    def _fange(self, aufruf):
        import io
        from contextlib import redirect_stdout

        puffer = io.StringIO()
        with redirect_stdout(puffer):
            aufruf()
        text = puffer.getvalue().strip()
        return json.loads(text) if text else None

    def test_claude_kontext(self):
        daten = self._fange(
            lambda: host.melde_kontext(host.CLAUDE, "SessionStart", "hallo")
        )
        self.assertEqual(
            daten["hookSpecificOutput"],
            {"hookEventName": "SessionStart", "additionalContext": "hallo"},
        )

    def test_antigravity_kontext(self):
        daten = self._fange(
            lambda: host.melde_kontext(host.ANTIGRAVITY, "PreInvocation", "hallo")
        )
        self.assertEqual(daten, {"injectSteps": [{"ephemeralMessage": "hallo"}]})

    def test_claude_werkzeughinweis_erlaubt_und_meldet(self):
        daten = self._fange(
            lambda: host.melde_werkzeug_hinweis(host.CLAUDE, "belegt", None)
        )
        self.assertEqual(daten["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(daten["hookSpecificOutput"]["additionalContext"], "belegt")

    def test_antigravity_werkzeughinweis_ist_nur_eine_erlaubnis(self):
        """
        Genau ein Feld, nichts sonst. Ein zusätzliches Feld kann der
        strenge Parser ablehnen, deshalb wandert der Hinweistext ins
        Postfach statt in die Antwort.
        """
        daten = self._fange(
            lambda: host.melde_werkzeug_hinweis(host.ANTIGRAVITY, "belegt", None)
        )
        self.assertEqual(daten, {"decision": "allow"})

    def test_claude_schweigt_wenn_nichts_anliegt(self):
        self.assertIsNone(self._fange(lambda: host.erlaube(host.CLAUDE)))
        self.assertIsNone(self._fange(lambda: host.fertig(host.CLAUDE)))

    def test_antigravity_antwortet_immer(self):
        self.assertEqual(self._fange(lambda: host.erlaube(host.ANTIGRAVITY)),
                         {"decision": "allow"})
        self.assertEqual(self._fange(lambda: host.fertig(host.ANTIGRAVITY)), {})


class TestPostfach(TeamTestCase):
    """
    Der zurückgestellte Hinweis.

    Unter Antigravity kann der Hinweis auf eine belegte Datei nicht aus
    dem Werkzeug-Hook kommen. Er wird abgelegt und beim nächsten
    Modellaufruf nachgereicht. Das darf weder etwas verschlucken noch
    dasselbe dreimal sagen.
    """

    personen = ("Lars",)

    def setUp(self):
        super().setUp()
        self.projekt = self.team.projekte["Lars"]

    def test_ablegen_und_abholen(self):
        host.postfach_legen(self.projekt, "erste Meldung")
        host.postfach_legen(self.projekt, "zweite Meldung")

        text = host.postfach_abholen(self.projekt)
        self.assertIn("erste Meldung", text)
        self.assertIn("zweite Meldung", text)

        # Danach ist es leer, sonst wiederholt sich die Meldung bei
        # jedem weiteren Aufruf und wird überlesen.
        self.assertEqual(host.postfach_abholen(self.projekt), "")

    def test_dieselbe_meldung_nur_einmal(self):
        for _ in range(3):
            host.postfach_legen(self.projekt, "belegt")
        self.assertEqual(host.postfach_abholen(self.projekt).count("belegt"), 1)

    def test_alte_meldungen_verfallen(self):
        import lib.channel as channel

        host.postfach_legen(self.projekt, "veraltet")
        pfad = channel.get_git_dir(self.projekt) / "team-sync-postfach.json"
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        daten["meldungen"][0]["zeit"] = time.time() - host.POSTFACH_GUELTIG - 60
        pfad.write_text(json.dumps(daten), encoding="utf-8")

        self.assertEqual(host.postfach_abholen(self.projekt), "")


class TestGemischtesTeam(TeamTestCase):
    """
    Der eigentliche Fall: eine Person mit Antigravity, zwei mit Claude
    Code, alle am selben Repository.
    """

    personen = ("Anna", "Ben", "Clara")

    def setUp(self):
        super().setUp()
        self.setup_alle()

    def _pull(self, person):
        git(["pull", "--rebase", "--quiet"], cwd=self.team.channels[person])

    def test_reservierung_aus_antigravity_warnt_claude_code(self):
        datei = self.team.projekte["Anna"] / "auth.py"
        datei.write_text("# auth\n", encoding="utf-8")

        ergebnis = self.team.ag_hook(
            "Anna", "tool_post_edit.py", self.team.ag_werkzeug("Anna", datei)
        )
        self.assertErfolg(ergebnis, "PostToolUse unter Antigravity")
        self.assertEqual(json.loads(ergebnis.stdout or "{}"), {})

        eigene = self.team.channel_datei("Anna", "reservierungen/anna.md")
        self.assertTrue(eigene.is_file(), "Antigravity hat nichts reserviert")
        self.assertIn("auth.py", eigene.read_text(encoding="utf-8"))

        self._pull("Ben")
        antwort = self.team.hook(
            "Ben",
            "tool_pre_edit.py",
            {
                "session_id": "b",
                "tool_name": "Edit",
                "permission_mode": "auto",
                "tool_input": {"file_path": str(self.team.projekte["Ben"] / "auth.py")},
            },
        )
        self.assertErfolg(antwort, "PreToolUse unter Claude Code")
        hinweis = json.loads(antwort.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("auth.py", hinweis)
        self.assertIn("anna", hinweis)

    def test_reservierung_aus_claude_code_erreicht_antigravity(self):
        datei = self.team.projekte["Ben"] / "api.py"
        datei.write_text("# api\n", encoding="utf-8")
        self.assertErfolg(
            self.team.hook(
                "Ben",
                "tool_post_edit.py",
                {
                    "session_id": "b",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(datei)},
                },
            )
        )

        self._pull("Anna")
        eigene = self.team.projekte["Anna"] / "api.py"

        vorher = self.team.ag_hook(
            "Anna", "tool_pre_edit.py", self.team.ag_werkzeug("Anna", eigene)
        )
        self.assertErfolg(vorher, "PreToolUse unter Antigravity")
        # Nur die Erlaubnis, der Hinweis kommt gleich über PreInvocation.
        self.assertEqual(json.loads(vorher.stdout), {"decision": "allow"})

        nachher = self.team.ag_hook(
            "Anna",
            "antigravity_hook.py",
            self.team.ag_invocation("Anna", unterhaltung="spaeter"),
            argv=("pre-invocation",),
        )
        self.assertErfolg(nachher, "PreInvocation unter Antigravity")
        schritte = json.loads(nachher.stdout).get("injectSteps", [])
        text = "\n".join(s.get("ephemeralMessage", "") for s in schritte)
        self.assertIn("api.py", text)
        self.assertIn("ben", text)

    def test_status_aus_antigravity_steht_in_der_uebersicht(self):
        datei = self.team.projekte["Anna"] / "models.py"
        datei.write_text("x\n", encoding="utf-8")
        self.team.ag_hook(
            "Anna", "tool_post_edit.py", self.team.ag_werkzeug("Anna", datei)
        )

        transkript = self.team.ag_transkript_schreiben(
            "Anna",
            [
                ag_nutzer_nachricht("Bau die Anmeldung auf JWT um"),
                ag_planer_antwort("Ich plane die Umstellung"),
            ],
        )
        ergebnis = self.team.ag_hook(
            "Anna",
            "antigravity_hook.py",
            self.team.ag_invocation("Anna", transkript),
            argv=("post-invocation",),
        )
        self.assertErfolg(ergebnis, "PostInvocation unter Antigravity")

        status = self.team.channel_datei("Anna", "status/anna.md").read_text(
            encoding="utf-8"
        )
        # Der Auftrag stammt aus einem fremden Transkriptformat, die
        # Dateiliste aus den eigenen Hooks. Beides muss ankommen.
        self.assertIn("JWT", status)
        self.assertIn("models.py", status)
        self.assertIn("werkzeug: Antigravity", status)

        self._pull("Clara")
        uebersicht = self.team.cli("Clara", "uebersicht")
        self.assertErfolg(uebersicht)
        self.assertIn("anna", uebersicht.stdout)
        self.assertIn("Antigravity", uebersicht.stdout)

    def test_frage_aus_claude_code_erreicht_antigravity(self):
        self.assertErfolg(
            self.team.cli(
                "Ben", "ask", "--to", "Anna", "--titel", "Sessions",
                "--text", "Wie laeuft die Sessionverwaltung im Frontend?",
            )
        )

        self._pull("Anna")
        ergebnis = self.team.ag_hook(
            "Anna",
            "antigravity_hook.py",
            self.team.ag_invocation("Anna", unterhaltung="neu"),
            argv=("pre-invocation",),
        )
        self.assertErfolg(ergebnis, "PreInvocation unter Antigravity")
        text = "\n".join(
            s.get("ephemeralMessage", "")
            for s in json.loads(ergebnis.stdout).get("injectSteps", [])
        )
        self.assertIn("Sessions", text)
        self.assertIn("ben", text)

    def test_antwort_aus_antigravity_erreicht_claude_code(self):
        """
        Die Rückrichtung. Ben fragt aus Claude Code, Anna antwortet aus
        Antigravity, und Ben erfährt davon, ohne seine Sitzung neu zu
        starten.
        """
        self.assertErfolg(
            self.team.cli(
                "Ben", "ask", "--to", "Anna", "--titel", "Cache",
                "--text", "Wird der Cache beim Deploy geleert?",
            )
        )
        self._pull("Anna")

        offen = self.team.cli("Anna", "fragen", "--json")
        self.assertErfolg(offen)
        fragen = json.loads(offen.stdout)
        self.assertEqual(len(fragen), 1, offen.stdout)

        self.assertErfolg(
            self.team.cli(
                "Anna", "answer", "--id", fragen[0]["id"], "--text", "Ja, beim Deploy."
            )
        )

        # Bei Ben liegt die Antwort danach im Channel, und seine Frage
        # zählt nicht mehr als offen.
        self._pull("Ben")
        wartend = self.team.cli("Ben", "fragen", "--gestellt", "--json")
        self.assertErfolg(wartend)
        self.assertEqual(json.loads(wartend.stdout), [])

        datei = self.team.channels["Ben"] / "questions" / f"{fragen[0]['id']}.md"
        self.assertIn("Ja, beim Deploy.", datei.read_text(encoding="utf-8"))

    def test_stop_gibt_reservierungen_frei(self):
        datei = self.team.projekte["Anna"] / "auth.py"
        datei.write_text("x\n", encoding="utf-8")
        self.team.ag_hook(
            "Anna", "tool_post_edit.py", self.team.ag_werkzeug("Anna", datei)
        )
        self.assertIn(
            "auth.py",
            self.team.channel_datei("Anna", "reservierungen/anna.md").read_text(
                encoding="utf-8"
            ),
        )

        ergebnis = self.team.ag_hook(
            "Anna",
            "antigravity_hook.py",
            self.team.ag_invocation("Anna"),
            argv=("stop",),
        )
        self.assertErfolg(ergebnis, "Stop unter Antigravity")
        self.assertNotIn(
            "auth.py",
            self.team.channel_datei("Anna", "reservierungen/anna.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_ohne_channel_passiert_nichts(self):
        """
        Wer die Hooks global einrichtet, hat sie auch in Projekten ohne
        Channel. Dort müssen sie still und schnell wieder aussteigen.
        """
        ohne = self.basis / "fremdes-projekt"
        ohne.mkdir()
        git(["init", "-q", "-b", "main", "."], cwd=ohne)

        ergebnis = self.team.ag_hook(
            "Anna",
            "antigravity_hook.py",
            {"conversationId": "x", "workspacePaths": [str(ohne)]},
            argv=("pre-invocation",),
        )
        self.assertEqual(ergebnis.returncode, 0)
        self.assertEqual(json.loads(ergebnis.stdout or "{}"), {})
        self.assertEqual(ergebnis.stderr.strip(), "")


class TestUnbekanntesEreignis(TeamTestCase):
    personen = ("Anna",)

    def test_falsches_argument_meldet_sich(self):
        ergebnis = self.team.ag_hook(
            "Anna", "antigravity_hook.py", {}, argv=("gibt-es-nicht",)
        )
        self.assertEqual(ergebnis.returncode, 1)
        self.assertIn("Unbekanntes Ereignis", ergebnis.stderr)
        self.assertEqual(ergebnis.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
