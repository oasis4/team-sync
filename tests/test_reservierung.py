"""
Tests für Reservierungen, Dateianfragen und den Rückkanal.

Der Ablauf, um den es geht, spielt sich zwischen zwei Sessions ab:
Eine reserviert eine Datei, die andere stößt darauf, fragt nach und
arbeitet weiter, die erste antwortet, die zweite erfährt es noch in
derselben Session. Genau diese Kette wird hier durchgespielt.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from helpers import SCRIPTS, TeamTestCase, git

sys.path.insert(0, str(SCRIPTS))


class ReservierungsTestCase(TeamTestCase):
    """Basis mit Hilfsmitteln für Werkzeug-Hooks."""

    def setUp(self):
        super().setUp()
        self.setup_alle()
        for person in self.personen:
            projekt = self.team.projekte[person]
            (projekt / "src").mkdir(exist_ok=True)

    def _payload(self, person, datei, tool="Edit", modus="default", session=None):
        return {
            "tool_name": tool,
            "session_id": session or f"s-{person.lower()}",
            "permission_mode": modus,
            "tool_input": {"file_path": str(self.team.projekte[person] / datei)},
        }

    def pre_edit(self, person, datei, modus="default", session=None, extra=None):
        """Ruft den PreToolUse-Hook auf, gibt den Meldungstext zurück."""
        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / "tool_pre_edit.py")],
            input=json.dumps(self._payload(person, datei, modus=modus, session=session)),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.team.projekte[person]),
            env=self.team.umgebung(person, extra),
        )
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
        if not ergebnis.stdout.strip():
            return None
        daten = json.loads(ergebnis.stdout)
        return daten["hookSpecificOutput"]

    def post_edit(self, person, datei, session=None):
        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / "tool_post_edit.py")],
            input=json.dumps(self._payload(person, datei, session=session)),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.team.projekte[person]),
            env=self.team.umgebung(person),
        )
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
        return ergebnis

    def stop_hook(self, person, extra=None):
        """Ruft den Stop-Hook auf, gibt den Rückkanal-Text zurück."""
        ergebnis = self.team.hook(
            person, "session_checkpoint.py",
            {"hook_event_name": "Stop", "session_id": f"s-{person.lower()}"},
            extra=extra,
        )
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
        if not ergebnis.stdout.strip():
            return ""
        return json.loads(ergebnis.stdout)["hookSpecificOutput"]["additionalContext"]

    def reservierungsdatei(self, person, besitzer):
        return self.team.channels[person] / "reservierungen" / f"{besitzer}.md"


class TestReservieren(ReservierungsTestCase):
    def test_erster_zugriff_reserviert(self):
        self.post_edit("Lars", "src/auth.py")

        inhalt = self.reservierungsdatei("Lars", "lars").read_text(encoding="utf-8")
        self.assertIn("src/auth.py", inhalt)
        self.assertIn("typ: reservierungen", inhalt)

    def test_pfad_wird_projektrelativ(self):
        """
        Ein absoluter Pfad wäre auf dem Rechner der anderen Person
        wertlos — dieselbe Datei ergäbe zwei Einträge und die Kollision
        fiele nie auf.
        """
        self.post_edit("Lars", "src/auth.py")

        inhalt = self.reservierungsdatei("Lars", "lars").read_text(encoding="utf-8")
        self.assertIn("`src/auth.py`", inhalt)
        self.assertNotIn(str(self.basis), inhalt)

    def test_zweiter_zugriff_erzeugt_keinen_commit(self):
        """Sonst entstünde pro Edit ein Commit und der Channel wäre unlesbar."""
        self.post_edit("Lars", "src/auth.py")
        channel = self.team.channels["Lars"]
        vorher = git(["rev-list", "--count", "HEAD"], cwd=channel).stdout.strip()

        for _ in range(3):
            self.post_edit("Lars", "src/auth.py")

        nachher = git(["rev-list", "--count", "HEAD"], cwd=channel).stdout.strip()
        self.assertEqual(vorher, nachher)

    def test_mehrere_dateien(self):
        self.post_edit("Lars", "src/auth.py")
        self.post_edit("Lars", "src/user.py")

        inhalt = self.reservierungsdatei("Lars", "lars").read_text(encoding="utf-8")
        self.assertIn("src/auth.py", inhalt)
        self.assertIn("src/user.py", inhalt)

    def test_andere_werkzeuge_reservieren_nicht(self):
        payload = self._payload("Lars", "src/auth.py", tool="Read")
        subprocess.run(
            [sys.executable, str(SCRIPTS / "tool_post_edit.py")],
            input=json.dumps(payload), capture_output=True, text=True,
            cwd=str(self.team.projekte["Lars"]), env=self.team.umgebung("Lars"),
        )
        self.assertFalse(self.reservierungsdatei("Lars", "lars").exists())


class TestWarnung(ReservierungsTestCase):
    def test_keine_warnung_ohne_fremde_reservierung(self):
        self.assertIsNone(self.pre_edit("Max", "src/auth.py"))

    def test_keine_warnung_fuer_eigene_reservierung(self):
        self.post_edit("Lars", "src/auth.py")
        self.assertIsNone(self.pre_edit("Lars", "src/auth.py"))

    def test_warnung_bei_fremder_reservierung(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")  # holt den Stand

        ausgabe = self.pre_edit("Max", "src/auth.py")
        self.assertIsNotNone(ausgabe, "Max bekam keine Warnung")
        self.assertIn("src/auth.py", ausgabe["additionalContext"])
        self.assertIn("lars", ausgabe["additionalContext"].lower())

    def test_warnung_blockiert_niemals(self):
        """
        Ein Hook, der verweigert, bringt eine Auto-Session unbemerkt zum
        Stehen. Das wäre schlimmer als die doppelte Arbeit.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        ausgabe = self.pre_edit("Max", "src/auth.py")
        self.assertEqual(ausgabe["permissionDecision"], "allow")

    def test_anderer_branch_nur_knapper_hinweis(self):
        """
        Auf verschiedenen Branches löst git das später. Eine dringliche
        Warnung wäre hier ein Fehlalarm, und nach dem dritten Fehlalarm
        wird sie überlesen.
        """
        self.post_edit("Lars", "src/auth.py")
        git(["checkout", "-q", "-b", "feature/zahlung"], cwd=self.team.projekte["Max"])
        self.team.cli("Max", "uebersicht")

        text = self.pre_edit("Max", "src/auth.py")["additionalContext"]
        self.assertIn("anderer Branch", text)
        self.assertNotIn("ist belegt", text)

    def test_gleicher_branch_fordert_zum_handeln_auf(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        text = self.pre_edit("Max", "src/auth.py", modus="auto")["additionalContext"]
        self.assertIn("ist belegt", text)
        self.assertIn("anfrage", text)
        self.assertIn("anderen Punkt weiter", text)

    def test_abgelaufene_reservierung_warnt_nicht(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        self.assertIsNotNone(self.pre_edit("Max", "src/auth.py"))
        # Mit Gültigkeit 0 gilt alles als abgelaufen.
        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / "tool_pre_edit.py")],
            input=json.dumps(self._payload("Max", "src/auth.py")),
            capture_output=True, text=True,
            cwd=str(self.team.projekte["Max"]),
            env=self.team.umgebung("Max", {"TEAM_SYNC_RESERVIERUNG_STUNDEN": "0"}),
        )
        self.assertEqual(ergebnis.stdout.strip(), "")

    def test_hook_laeuft_schnell(self):
        """
        Der Hook läuft vor jedem einzelnen Edit. Wird er langsam, fällt
        das nicht als Fehler auf, sondern nur als zähe Session — und
        dann sucht niemand hier.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        start = time.time()
        for _ in range(3):
            self.pre_edit("Max", "src/auth.py")
        dauer = (time.time() - start) / 3

        # Großzügig: Der Python-Start allein braucht auf langsamen
        # Rechnern schon einen Moment. Es geht darum, einen versehentlich
        # eingebauten Netzwerkaufruf zu bemerken, nicht um Feintuning.
        self.assertLess(dauer, 2.0, f"PreToolUse-Hook braucht {dauer:.2f}s pro Aufruf")


class TestFreigabe(ReservierungsTestCase):
    def test_freigeben_einzeln(self):
        self.post_edit("Lars", "src/auth.py")
        self.post_edit("Lars", "src/user.py")

        ergebnis = self.team.cli("Lars", "freigeben", "--datei", "src/auth.py")
        self.assertErfolg(ergebnis)

        inhalt = self.reservierungsdatei("Lars", "lars").read_text(encoding="utf-8")
        self.assertNotIn("src/auth.py", inhalt)
        self.assertIn("src/user.py", inhalt)

    def test_sessionende_gibt_alles_frei(self):
        """
        Ohne das hält eine beendete Session ihre Dateien stundenlang
        besetzt, und die anderen bekommen Warnungen vor jemandem, der
        längst Feierabend hat.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.hook("Lars", "session_end.py", {"session_end_reason": "logout"})

        inhalt = self.reservierungsdatei("Lars", "lars").read_text(encoding="utf-8")
        self.assertNotIn("src/auth.py", inhalt)

        self.team.cli("Max", "uebersicht")
        self.assertIsNone(self.pre_edit("Max", "src/auth.py"))

    def test_uebersicht_zeigt_reservierungen(self):
        self.post_edit("Lars", "src/auth.py")
        ergebnis = self.team.cli("Max", "reservierungen", "--json")
        self.assertErfolg(ergebnis)

        daten = json.loads(ergebnis.stdout)
        self.assertEqual(len(daten["fremde"]), 1)
        self.assertEqual(daten["fremde"][0]["datei"], "src/auth.py")
        self.assertEqual(daten["eigene"], [])


class TestAnfragen(ReservierungsTestCase):
    def test_anfrage_erreicht_den_besitzer(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        ergebnis = self.team.cli(
            "Max", "anfrage", "--datei", "src/auth.py", "--text", "Token-Prüfung"
        )
        self.assertErfolg(ergebnis)
        self.assertIn("abgelegt", ergebnis.stdout)

        offen = json.loads(self.team.cli("Lars", "fragen", "--json").stdout)
        self.assertEqual(len(offen), 1)
        self.assertIn("src/auth.py", offen[0]["titel"])

    def test_anfrage_raet_nicht_zum_warten(self):
        """
        Warten kostet genau die Zeit, die gespart werden soll. Die
        Rückmeldung muss zum Weiterarbeiten auffordern.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        ergebnis = self.team.cli("Max", "anfrage", "--datei", "src/auth.py")
        self.assertIn("Nicht warten", ergebnis.stdout)

    def test_keine_anfrage_ohne_reservierung(self):
        ergebnis = self.team.cli("Max", "anfrage", "--datei", "src/frei.py")
        self.assertErfolg(ergebnis)
        self.assertIn("von niemandem reserviert", ergebnis.stdout)

    def test_zweite_anfrage_wird_unterdrueckt(self):
        """Sonst ersäuft der Channel bei jedem weiteren Edit."""
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")

        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")
        zweite = self.team.cli("Max", "anfrage", "--datei", "src/auth.py")
        self.assertIn("bereits", zweite.stdout)

        self.team.cli("Lars", "uebersicht")
        dateien = list((self.team.channels["Lars"] / "questions").glob("*.md"))
        self.assertEqual(len(dateien), 1, [d.name for d in dateien])

    def test_sperre_greift_ueber_werkzeuggrenzen_hinweg(self):
        """
        Die Anfrage kommt über die Kommandozeile, die Prüfung aus dem
        Hook. Hingen beide an einer Sitzungskennung, würde der Riegel
        nicht greifen — der Hook kennt sie aus seiner Payload, das
        Kommandozeilenwerkzeug kennt sie nicht. Genau so war es zuerst,
        und es hätte eine Anfrage pro Edit erzeugt.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        # Anfrage als verfallen behandeln, damit nicht schon der Zweig
        # "läuft bereits" greift, und mit einer anderen Sitzungskennung
        # aufrufen als die Kommandozeile sie hatte.
        text = self.pre_edit(
            "Max", "src/auth.py",
            session="voellig-andere-id",
            extra={"TEAM_SYNC_ANFRAGE_TIMEOUT": "0"},
        )
        self.assertIn("bereits danach gefragt", text["additionalContext"])

    def test_laufende_anfrage_wird_im_hook_gemeldet(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        text = self.pre_edit("Max", "src/auth.py")["additionalContext"]
        self.assertIn("läuft bereits", text)

    def test_verfallene_anfrage_gibt_die_datei_frei(self):
        """
        Die Gegenseite kann eine tote Session sein. Wer ewig auf eine
        Antwort wartet, wartet auf niemanden.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        ergebnis = subprocess.run(
            [sys.executable, str(SCRIPTS / "tool_pre_edit.py")],
            input=json.dumps(self._payload("Max", "src/auth.py")),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.team.projekte["Max"]),
            env=self.team.umgebung("Max", {"TEAM_SYNC_ANFRAGE_TIMEOUT": "0"}),
        )
        text = json.loads(ergebnis.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("keine Antwort", text)

    def test_beantwortete_anfrage_erscheint_im_hook(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        frage_id = json.loads(self.team.cli("Lars", "fragen", "--json").stdout)[0]["id"]
        self.team.cli(
            "Lars", "answer", "--id", frage_id,
            "--text", "Ich bin nur in verify_token, der Rest ist frei.",
        )
        self.team.cli("Max", "uebersicht")

        text = self.pre_edit("Max", "src/auth.py")["additionalContext"]
        self.assertIn("verify_token", text)
        self.assertIn("beantwortet", text)
        # Die eigene Frage soll nicht mit zurückkommen.
        self.assertNotIn("Antwort bitte zügig", text)


class TestRueckkanal(ReservierungsTestCase):
    def test_meldet_neue_frage(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        text = self.stop_hook("Lars")
        self.assertIn("src/auth.py", text)
        self.assertIn("max", text.lower())

    def test_meldet_antwort_an_den_fragenden(self):
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        frage_id = json.loads(self.team.cli("Lars", "fragen", "--json").stdout)[0]["id"]
        self.team.cli("Lars", "answer", "--id", frage_id, "--text", "Nur in verify_token.")

        text = self.stop_hook("Max")
        self.assertIn("verify_token", text)

    def test_meldet_nichts_zweimal(self):
        """
        Eine Meldung, die sich bei jedem Durchlauf wiederholt, wird nach
        dem zweiten Mal ignoriert — und dann auch die wichtige.
        """
        self.post_edit("Lars", "src/auth.py")
        self.team.cli("Max", "uebersicht")
        self.team.cli("Max", "anfrage", "--datei", "src/auth.py")

        erste = self.stop_hook("Lars")
        self.assertTrue(erste)

        zweite = self.stop_hook("Lars", extra={"TEAM_SYNC_EMPFANG_SECONDS": "0"})
        self.assertEqual(zweite, "")

    def test_meldet_neue_entscheidung(self):
        self.team.cli("Lars", "decide", "--titel", "Postgres", "--entscheidung", "Postgres.")
        text = self.stop_hook("Max")
        self.assertIn("Postgres", text)

    def test_eigene_entscheidung_wird_nicht_gemeldet(self):
        self.team.cli("Lars", "decide", "--titel", "Postgres", "--entscheidung", "Postgres.")
        self.assertEqual(self.stop_hook("Lars"), "")

    def test_sessionstart_schaltet_bekanntes_stumm(self):
        """
        Sonst wiederholt die erste Meldung, was der Startkontext gerade
        schon geliefert hat.
        """
        self.team.cli("Lars", "decide", "--titel", "Redis", "--entscheidung", "Redis.")
        self.team.hook("Max", "session_start.py", {"hook_event_name": "SessionStart"})

        self.assertEqual(self.stop_hook("Max"), "")

    def test_empfang_ist_gedrosselt(self):
        self.team.cli("Lars", "decide", "--titel", "Kafka", "--entscheidung", "Kafka.")
        self.assertIn("Kafka", self.stop_hook("Max"))

        self.team.cli("Lars", "decide", "--titel", "Nginx", "--entscheidung", "Nginx.")
        # Der zweite Durchlauf kommt zu früh und sieht deshalb nichts.
        self.assertEqual(self.stop_hook("Max"), "")


class TestOhneChannel(TeamTestCase):
    """Ohne eingerichteten Channel dürfen die Hooks nichts tun."""

    def test_hooks_bleiben_still(self):
        projekt = self.team.projekte["Lars"]
        payload = {
            "tool_name": "Edit",
            "session_id": "s1",
            "tool_input": {"file_path": str(projekt / "datei.py")},
        }
        for skript in ("tool_pre_edit.py", "tool_post_edit.py"):
            ergebnis = subprocess.run(
                [sys.executable, str(SCRIPTS / skript)],
                input=json.dumps(payload), capture_output=True, text=True,
                cwd=str(projekt), env=self.team.umgebung("Lars"),
            )
            self.assertEqual(ergebnis.returncode, 0, f"{skript}: {ergebnis.stderr}")
            self.assertEqual(ergebnis.stdout.strip(), "", skript)

    def test_hooks_ueberstehen_muell(self):
        for skript in ("tool_pre_edit.py", "tool_post_edit.py"):
            for eingabe in ("", "kein json", '{"tool_name":"Edit"}', "{}"):
                ergebnis = subprocess.run(
                    [sys.executable, str(SCRIPTS / skript)],
                    input=eingabe, capture_output=True, text=True,
                    cwd=str(self.team.projekte["Lars"]),
                    env=self.team.umgebung("Lars"),
                )
                self.assertEqual(
                    ergebnis.returncode, 0,
                    f"{skript} stieg bei {eingabe!r} aus: {ergebnis.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
