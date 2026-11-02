"""
Tests für 0.5: Namen, Nachrichten, Rückweg von Antworten, Lauscher,
Hook vor jeder Eingabe und das abgelöste Sessionende.

Jeder Abschnitt hier hängt an einem Fehler, der bis 0.4 im Alltag
aufgetreten wäre, ohne dass ein Test ihn bemerkt hat. Die alten Tests
setzen TEAM_AGENT_NAME auf einen Kurznamen und CLAUDE_PLUGIN_ROOT in
jeder Umgebung. Im echten Betrieb ist beides nicht so, und genau dort
lagen die Fehler.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from helpers import SCRIPTS, TeamTestCase, git

sys.path.insert(0, str(SCRIPTS))

from lib import frontmatter, nachrichten  # noqa: E402


def zusatztext(ergebnis):
    """additionalContext aus einer Hook-Ausgabe, oder ""."""
    if not ergebnis.stdout.strip():
        return ""
    return json.loads(ergebnis.stdout)["hookSpecificOutput"]["additionalContext"]


class LiveTestCase(TeamTestCase):
    """Drei Personen, zwei davon mit vollem Namen wie aus git config."""

    personen = ("Lars", "Max", "Mia")
    namen = {"Max": "Max Mustermann", "Mia": "Mia Wagner"}

    def setUp(self):
        super().setUp()
        self.team.anzeigenamen.update(self.namen)
        self.setup_alle()

    def slug(self, person):
        from lib.channel import slugify

        return slugify(self.team.anzeigenamen.get(person, person))

    def empfang(self, person, extra=None):
        """Nur der Rückkanal des Stop-Hooks, wie in hooks.json eingetragen."""
        umgebung = {"TEAM_SYNC_EMPFANG_SECONDS": "0"}
        umgebung.update(extra or {})
        ergebnis = self.team.hook(
            person, "session_checkpoint.py", {"hook_event_name": "Stop"},
            extra=umgebung, argv=("empfang",),
        )
        self.assertErfolg(ergebnis)
        return zusatztext(ergebnis)

    def eingabe(self, person):
        """Der UserPromptSubmit-Hook."""
        ergebnis = self.team.hook(
            person, "prompt_submit.py",
            {"hook_event_name": "UserPromptSubmit", "prompt": "weiter"},
        )
        self.assertErfolg(ergebnis)
        if ergebnis.stdout.strip():
            daten = json.loads(ergebnis.stdout)["hookSpecificOutput"]
            self.assertEqual(daten["hookEventName"], "UserPromptSubmit")
            return daten["additionalContext"]
        return ""


# ---------------------------------------------------------------------------
# Namen
# ---------------------------------------------------------------------------


class TestNamen(LiveTestCase):
    def test_vorname_erreicht_den_vollen_namen(self):
        """
        Der Fehler, der bis 0.4 jede /ask-Frage im Alltag verschluckt hat:
        Das README zeigt '/ask max', im Channel heißt Max aber
        'max-mustermann'.
        """
        ergebnis = self.team.cli("Lars", "ask", "--to", "max", "--text", "Wie geht X?")
        self.assertErfolg(ergebnis)
        self.assertIn("max-mustermann", ergebnis.stdout)
        self.assertNotIn("niemand namens", ergebnis.stdout)

        fragen = json.loads(self.team.cli("Max", "fragen", "--json").stdout)
        self.assertEqual(len(fragen), 1)
        self.assertEqual(fragen[0]["an"], "max-mustermann")

    def test_nachname_reicht_auch(self):
        self.team.cli("Lars", "ask", "--to", "Wagner", "--text", "Frage")
        fragen = json.loads(self.team.cli("Mia", "fragen", "--json").stdout)
        self.assertEqual(len(fragen), 1)

    def test_setup_macht_den_namen_bekannt(self):
        """Wer nur eingerichtet hat, ist trotzdem schon auffindbar."""
        status = self.team.channel_datei("Lars", "status/max-mustermann.md")
        self.team.cli("Lars", "uebersicht")
        self.assertTrue(status.is_file())
        self.assertIn("quelle: eingerichtet", status.read_text(encoding="utf-8"))

    def test_status_aus_dem_setup_steht_nicht_im_kontext(self):
        """Er trägt nur einen Namen und kostet sonst nur Tokens."""
        ergebnis = self.team.hook("Lars", "session_start.py", {})
        self.assertNotIn("Woran die anderen", zusatztext(ergebnis))

    def test_unbekannter_name_wird_laut_gemeldet(self):
        ergebnis = self.team.cli("Lars", "ask", "--to", "moritz", "--text", "Hallo?")
        self.assertErfolg(ergebnis)
        self.assertIn("niemand namens 'moritz'", ergebnis.stdout)
        self.assertIn("max-mustermann", ergebnis.stdout)

    def test_mehrdeutiger_name_bricht_ab(self):
        self.team.anzeigenamen["Lars"] = "Max Meier"
        self.team.cli("Lars", "sync", "--text", "Ich heiße jetzt anders")
        ergebnis = self.team.cli("Mia", "ask", "--to", "max", "--text", "Welcher?")
        self.assertEqual(ergebnis.returncode, 1)
        self.assertIn("max-meier", ergebnis.stderr)
        self.assertIn("max-mustermann", ergebnis.stderr)

    def test_frage_an_sich_selbst_wird_abgelehnt(self):
        ergebnis = self.team.cli("Max", "ask", "--to", "max", "--text", "Ich?")
        self.assertEqual(ergebnis.returncode, 1)

    def test_frage_an_alle(self):
        self.team.cli("Lars", "ask", "--to", "alle", "--text", "Wer kennt Kafka?")
        for person in ("Max", "Mia"):
            fragen = json.loads(self.team.cli(person, "fragen", "--json").stdout)
            self.assertEqual(len(fragen), 1, person)
        # Die eigene Frage an alle ist keine offene Frage an sich selbst.
        self.assertEqual(json.loads(self.team.cli("Lars", "fragen", "--json").stdout), [])


class TestNamensvergleich(unittest.TestCase):
    def test_namensteile(self):
        self.assertTrue(frontmatter.matches_person("max", "max-mustermann"))
        self.assertTrue(frontmatter.matches_person("mustermann", "Max Mustermann"))
        self.assertFalse(frontmatter.matches_person("maxi", "max-mustermann"))
        self.assertFalse(frontmatter.matches_person("max-mustermann", "max"))

    def test_alle_nur_auf_wunsch(self):
        self.assertFalse(frontmatter.matches_person("alle", "max"))
        self.assertTrue(frontmatter.matches_person("alle", "max", alle=True))
        self.assertTrue(frontmatter.matches_person("lars, all", "max", alle=True))


# ---------------------------------------------------------------------------
# Nachrichten
# ---------------------------------------------------------------------------


class TestErwaehnungen(unittest.TestCase):
    def test_namen_im_text(self):
        self.assertEqual(
            nachrichten.erwaehnungen("@max und @Jörg, bitte. Danke @max."),
            ["max", "Jörg"],
        )

    def test_mailadresse_ist_keine_erwaehnung(self):
        self.assertEqual(nachrichten.erwaehnungen("schreib an max@example.com"), [])

    def test_satzzeichen_gehoert_nicht_zum_namen(self):
        self.assertEqual(nachrichten.erwaehnungen("Fertig, @lars."), ["lars"])


class TestNachrichten(LiveTestCase):
    def test_nachricht_erreicht_nur_den_empfaenger(self):
        ergebnis = self.team.cli(
            "Lars", "post", "--text", "@max Login ist gemergt, die API-Route ist frei."
        )
        self.assertErfolg(ergebnis)
        self.assertIn("an max-mustermann", ergebnis.stdout)

        self.assertIn("Login ist gemergt", self.empfang("Max"))
        self.assertEqual(self.empfang("Mia"), "")
        self.assertEqual(self.empfang("Lars"), "")

    def test_ohne_erwaehnung_an_alle(self):
        self.team.cli("Lars", "post", "--text", "DB_URL heißt jetzt DATABASE_URL.")
        self.assertIn("DATABASE_URL", self.empfang("Max"))
        self.assertIn("DATABASE_URL", self.empfang("Mia"))
        # Wer an alle schreibt, bekommt es nicht zurückgemeldet.
        self.assertEqual(self.empfang("Lars"), "")

    def test_meldung_kommt_nur_einmal(self):
        self.team.cli("Lars", "post", "--text", "@mia Schema ist fertig.")
        self.assertIn("Schema", self.empfang("Mia"))
        self.assertEqual(self.empfang("Mia"), "")
        self.assertEqual(self.eingabe("Mia"), "")

    def test_meldung_enthaelt_regeln_und_antwortweg(self):
        self.team.cli("Lars", "post", "--text", "@max Bitte übernimm die Route.")
        text = self.empfang("Max")
        self.assertIn("nur, um zu bestätigen", text)
        self.assertIn("dein Nutzer", text)
        self.assertIn(" post --text", text)

    def test_sessionstart_zeigt_ungelesene_nachricht(self):
        self.team.cli("Lars", "post", "--text", "@max Merge bitte erst nach 16 Uhr.")
        text = zusatztext(self.team.hook("Max", "session_start.py", {}))
        self.assertIn("16 Uhr", text)
        # Danach gilt sie als gesehen.
        self.assertEqual(self.empfang("Max"), "")

    def test_nachrichten_auflisten(self):
        self.team.cli("Lars", "post", "--text", "@max Eins")
        self.team.cli("Mia", "post", "--text", "@lars Zwei")
        an_max = self.team.cli("Max", "nachrichten").stdout
        self.assertIn("Eins", an_max)
        self.assertNotIn("Zwei", an_max)
        alle = self.team.cli("Max", "nachrichten", "--alle").stdout
        self.assertIn("Zwei", alle)

    def test_uebersicht_zeigt_letzte_nachrichten(self):
        self.team.cli("Lars", "post", "--text", "@mia Release-Branch ist angelegt.")
        self.assertIn("Release-Branch", self.team.cli("Max", "uebersicht").stdout)

    def test_zwei_nachrichten_in_derselben_sekunde(self):
        self.team.cli("Lars", "post", "--text", "@max Erste")
        self.team.cli("Lars", "post", "--text", "@max Zweite")
        text = self.empfang("Max")
        self.assertIn("Erste", text)
        self.assertIn("Zweite", text)


# ---------------------------------------------------------------------------
# Rückweg von Antworten
# ---------------------------------------------------------------------------


class TestAntwortRueckweg(LiveTestCase):
    def frage_und_antwort(self):
        self.team.cli("Lars", "ask", "--to", "max", "--titel", "Sessions",
                      "--text", "Wie laufen die Sessions?")
        frage = json.loads(self.team.cli("Max", "fragen", "--json").stdout)[0]
        self.team.cli("Max", "answer", "--id", frage["id"],
                      "--text", "Über einen Context in session.tsx.")

    def test_antwort_auf_normale_frage_kommt_beim_fragenden_an(self):
        """Bis 0.4 kam das nur bei Dateianfragen zurück."""
        self.frage_und_antwort()
        text = self.empfang("Lars")
        self.assertIn("session.tsx", text)
        self.assertIn("Sessions", text)

    def test_antwort_steht_im_naechsten_sessionstart(self):
        self.frage_und_antwort()
        text = zusatztext(self.team.hook("Lars", "session_start.py", {}))
        self.assertIn("Antworten auf deine Fragen", text)
        self.assertIn("session.tsx", text)
        # Und danach nicht noch einmal.
        self.assertEqual(self.empfang("Lars"), "")
        text = zusatztext(self.team.hook("Lars", "session_start.py", {}))
        self.assertNotIn("session.tsx", text)


# ---------------------------------------------------------------------------
# Befehle in Hook-Texten
# ---------------------------------------------------------------------------


class TestBefehleImText(LiveTestCase):
    def belegen(self):
        projekt = self.team.projekte["Lars"]
        (projekt / "src").mkdir(exist_ok=True)
        payload = {
            "tool_name": "Edit", "session_id": "s1",
            "tool_input": {"file_path": str(projekt / "src" / "auth.py")},
        }
        self.assertErfolg(self.team.hook("Lars", "tool_post_edit.py", payload))
        self.team.cli("Max", "uebersicht")

        ziel = self.team.projekte["Max"] / "src" / "auth.py"
        payload = {
            "tool_name": "Edit", "session_id": "s2", "permission_mode": "auto",
            "tool_input": {"file_path": str(ziel)},
        }
        ergebnis = self.team.hook("Max", "tool_pre_edit.py", payload)
        return json.loads(ergebnis.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_hinweis_nennt_den_echten_pfad(self):
        """
        Bis 0.4 stand hier ${CLAUDE_PLUGIN_ROOT}. In Claudes Shell ist
        die Variable leer, der Befehl lief ins Leere, und keine einzige
        Dateianfrage kam je zustande.
        """
        text = self.belegen()
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", text)
        self.assertIn((SCRIPTS / "team_sync.py").resolve().as_posix(), text)

    @unittest.skipIf(shutil.which("bash") is None, "keine bash vorhanden")
    def test_befehl_aus_dem_hinweis_laeuft_in_einer_shell(self):
        text = self.belegen()
        zeile = next(z for z in text.splitlines() if "anfrage --datei" in z).strip()
        befehl = zeile.replace("<was du vorhast>", "Ich baue die Middleware um")

        umgebung = self.team.umgebung("Max")
        umgebung.pop("CLAUDE_PLUGIN_ROOT", None)
        ergebnis = subprocess.run(
            ["bash", "-c", befehl], cwd=str(self.team.projekte["Max"]),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=umgebung,
        )
        self.assertErfolg(ergebnis, befehl)
        self.assertIn("Anfrage an lars", ergebnis.stdout)

    def test_antwortbefehl_im_rueckkanal_hat_einen_pfad(self):
        self.team.cli("Lars", "ask", "--to", "mia", "--text", "Frage?")
        text = self.empfang("Mia")
        zeile = next(z for z in text.splitlines() if "answer --id" in z)
        self.assertIn((SCRIPTS / "team_sync.py").resolve().as_posix(), zeile)


# ---------------------------------------------------------------------------
# Hook vor jeder Eingabe
# ---------------------------------------------------------------------------


class TestEingabeHook(LiveTestCase):
    def test_liest_nur_lokal(self):
        """
        Kein Netz vor jeder Eingabe. Was noch nicht gezogen ist, kommt
        über den Lauscher oder den Stop-Hook.
        """
        self.team.cli("Lars", "post", "--text", "@max Neu")
        self.assertEqual(self.eingabe("Max"), "")

        self.team.cli("Max", "uebersicht")  # zieht
        self.assertIn("Neu", self.eingabe("Max"))

    def test_still_ohne_channel(self):
        ergebnis = self.team.hook("Lars", "prompt_submit.py", {"prompt": "x"},
                                  extra={"TEAM_SYNC_CHANNEL_DIR": str(self.basis / "fehlt")})
        self.assertErfolg(ergebnis)
        self.assertEqual(ergebnis.stdout.strip(), "")

    def test_ueberlebt_muell(self):
        for eingabe in ("", "kein json", "{}"):
            ergebnis = subprocess.run(
                [sys.executable, str(SCRIPTS / "prompt_submit.py")],
                input=eingabe, capture_output=True, text=True,
                cwd=str(self.team.projekte["Lars"]), env=self.team.umgebung("Lars"),
            )
            self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)


# ---------------------------------------------------------------------------
# Lauscher und warten
# ---------------------------------------------------------------------------


class TestLauscher(LiveTestCase):
    def starte(self, person, *argv, skript="team_sync.py", extra=None):
        return subprocess.Popen(
            [sys.executable, str(SCRIPTS / skript)] + list(argv),
            cwd=str(self.team.projekte[person]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=self.team.umgebung(person, extra),
        )

    def beenden(self, prozess):
        if prozess.poll() is None:
            prozess.kill()
        return prozess.communicate(timeout=10)

    def test_warten_kehrt_bei_einer_nachricht_zurueck(self):
        """Das Gegenstück zu 'tools/board wait'."""
        self.team.hook("Max", "session_start.py", {})
        prozess = self.starte("Max", "warten", "--intervall", "1", "--timeout", "40")
        time.sleep(1.5)
        self.team.cli("Lars", "post", "--text", "@max Bin fertig mit dem Login.")

        try:
            ausgabe, fehler = prozess.communicate(timeout=45)
        finally:
            self.beenden(prozess)
        self.assertEqual(prozess.returncode, 0, fehler)
        self.assertIn("Bin fertig mit dem Login", ausgabe)

    def test_warten_meldet_bereits_vorliegendes_sofort(self):
        self.team.cli("Lars", "post", "--text", "@max Liegt schon da.")
        ergebnis = self.team.cli("Max", "warten", "--intervall", "1", "--timeout", "20")
        self.assertErfolg(ergebnis)
        self.assertIn("Liegt schon da", ergebnis.stdout)

    def test_warten_mit_ablauf(self):
        self.team.hook("Max", "session_start.py", {})
        ergebnis = self.team.cli("Max", "warten", "--intervall", "1", "--timeout", "2")
        self.assertEqual(ergebnis.returncode, 124)
        self.assertEqual(ergebnis.stdout.strip(), "")

    def test_monitor_meldet_eine_nachricht(self):
        self.team.hook("Max", "session_start.py", {})
        prozess = self.starte(
            "Max", str(self.team.projekte["Max"]), skript="lauschen.py",
            extra={"TEAM_SYNC_LAUSCHEN_SECONDS": "5", "TEAM_SYNC_LAUSCHEN_START": "0"},
        )
        # Gemeldet ist die Nachricht, sobald sie in der Merkliste des
        # Rückkanals steht. Danach den Monitor beenden und lesen.
        merkliste = self.team.projekte["Max"] / ".git" / "team-sync-empfang.json"
        try:
            time.sleep(1.5)
            self.team.cli("Lars", "post", "--text", "@max Monitor-Test")
            frist = time.time() + 30
            while time.time() < frist:
                try:
                    if "nachricht:" in merkliste.read_text(encoding="utf-8"):
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            time.sleep(1)
        finally:
            ausgabe, _ = self.beenden(prozess)
        self.assertIn("Monitor-Test", ausgabe)

    def test_monitor_ohne_channel_bleibt_still_und_endet_nicht(self):
        """
        Ein Monitor, der sich beendet, wird in der Session gemeldet. In
        jedem Projekt ohne Channel wäre das eine sinnlose Meldung.
        """
        prozess = self.starte(
            "Lars", skript="lauschen.py",
            extra={"TEAM_SYNC_CHANNEL_DIR": str(self.basis / "fehlt")},
        )
        time.sleep(2)
        self.assertIsNone(prozess.poll())
        ausgabe, _ = self.beenden(prozess)
        self.assertEqual(ausgabe.strip(), "")

    def test_abgeschaltet(self):
        self.team.cli("Lars", "post", "--text", "@max Hallo")
        prozess = self.starte(
            "Max", skript="lauschen.py",
            extra={"TEAM_SYNC_LAUSCHEN": "aus", "TEAM_SYNC_LAUSCHEN_START": "0"},
        )
        time.sleep(2)
        self.assertIsNone(prozess.poll())
        ausgabe, _ = self.beenden(prozess)
        self.assertEqual(ausgabe.strip(), "")

    @unittest.skipIf(os.name == "nt", "Unter Windows gilt die Obergrenze von einem Tag")
    def test_monitor_endet_nach_absturz_der_session(self):
        """
        Claude Code startet den Monitor über eine Shell. Stirbt Claude
        Code hart, überlebt die Shell, und ein Lauscher, der nur seinen
        direkten Elternprozess beobachtet, läuft ewig weiter. Genau das
        ist im Test mit einer echten Sitzung passiert.
        """
        self.team.hook("Max", "session_start.py", {})
        lauscher = SCRIPTS / "lauschen.py"
        pid_datei = self.basis / "lauscher.pid"
        # Ein Ersatz für Claude Code, der eine Shell startet, die den
        # Lauscher startet und dessen PID ablegt.
        session = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys, time\n"
             f"subprocess.Popen(['sh', '-c', '{sys.executable} "
             f"\"{lauscher}\" & echo $! > \"{pid_datei}\"; wait'])\n"
             "time.sleep(120)\n"],
            cwd=str(self.team.projekte["Max"]),
            env=self.team.umgebung("Max", {
                "TEAM_SYNC_LAUSCHEN_SECONDS": "5", "TEAM_SYNC_LAUSCHEN_START": "0",
            }),
        )
        try:
            frist = time.time() + 15
            while time.time() < frist and not pid_datei.exists():
                time.sleep(0.2)
            time.sleep(1.5)
            pid = int(pid_datei.read_text().strip())
            self.assertTrue(self._lebt(pid), "Der Lauscher ist gar nicht erst gestartet")

            session.kill()
            session.wait(timeout=10)

            frist = time.time() + 20
            while time.time() < frist and self._lebt(pid):
                time.sleep(0.5)
            self.assertFalse(self._lebt(pid), "Der Lauscher läuft nach dem Absturz weiter")
        finally:
            if session.poll() is None:
                session.kill()
            try:
                os.kill(int(pid_datei.read_text().strip()), 9)
            except Exception:
                pass

    @staticmethod
    def _lebt(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        # Ein beendeter, aber noch nicht abgeholter Prozess zählt als tot.
        try:
            status = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            return status != "Z"
        except Exception:
            return True

    def test_stop_hook_zieht_nicht_neben_einem_lauscher(self):
        """Läuft ein Lauscher, verlässt sich der Stop-Hook auf ihn."""
        self.team.hook("Max", "session_start.py", {})
        self.team.cli("Lars", "post", "--text", "@max Neu")

        lebenszeichen = self.team.projekte["Max"] / ".git" / "team-sync-lauscher"
        lebenszeichen.touch()
        self.assertEqual(self.empfang("Max"), "")

        lebenszeichen.unlink()
        self.assertIn("Neu", self.empfang("Max"))


# ---------------------------------------------------------------------------
# Sessionende
# ---------------------------------------------------------------------------


class TestSessionende(LiveTestCase):
    def test_hook_kehrt_sofort_zurueck_und_schreibt_trotzdem(self):
        """
        Claude Code gibt SessionEnd-Hooks 1,5 Sekunden. Bis 0.4 reichte
        das nie für Status und Freigabe.
        """
        projekt = self.team.projekte["Lars"]
        (projekt / "src").mkdir(exist_ok=True)
        self.team.hook("Lars", "tool_post_edit.py", {
            "tool_name": "Edit", "session_id": "s1",
            "tool_input": {"file_path": str(projekt / "src" / "a.py")},
        })

        beginn = time.time()
        ergebnis = self.team.hook(
            "Lars", "session_end.py", {"reason": "prompt_input_exit"},
            argv=("--abgeloest-testen",),
        )
        dauer = time.time() - beginn
        self.assertErfolg(ergebnis)
        self.assertLess(dauer, 1.5, f"SessionEnd-Hook brauchte {dauer:.2f} s")

        # Fertig ist der abgelöste Prozess, wenn die Freigabe beim Remote liegt.
        frist = time.time() + 40
        while time.time() < frist:
            log = git(["log", "--format=%s", "team-channel"], cwd=self.team.remote,
                      check=False).stdout
            if "freigegeben: lars - alle" in log:
                break
            time.sleep(0.5)
        else:
            self.fail("Der abgelöste Prozess hat nicht freigegeben")
        self.assertIn("status: lars", log)
        time.sleep(0.5)

    def test_grund_wird_gelesen(self):
        """Das Feld heißt 'reason'. Bis 0.4 wurde ein anderes gelesen."""
        self.team.hook("Lars", "session_end.py", {"reason": "clear"})
        log = git(["log", "--format=%s", "-3"], cwd=self.team.channels["Lars"]).stdout
        self.assertIn("Sessionwechsel (clear)", log)


if __name__ == "__main__":
    unittest.main()
