"""
Das Setup für Antigravity.

Hier geht es um fremde Konfigurationsdateien, und das ist der Grund für
den Umfang dieser Datei. Ein Plugin, das die hooks.json einer anderen
Person überschreibt, richtet mehr Schaden an als es Nutzen bringt.
Geprüft wird deshalb vor allem, was das Skript NICHT anfasst.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import SCRIPTS, TeamTestCase  # noqa: E402

FREMDE_GRUPPE = {
    "mein-linter": {
        "PostToolUse": [
            {"matcher": "run_command", "hooks": [{"type": "command", "command": "./lint.sh"}]}
        ]
    }
}


class AntigravitySetupTestCase(TeamTestCase):
    personen = ("Anna",)

    def setUp(self):
        super().setUp()
        self.projekt = self.team.projekte["Anna"]
        self.agents = self.projekt / ".agents"

    def setup_ag(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "setup_antigravity.py")] + list(args),
            cwd=str(self.projekt),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.team.umgebung("Anna"),
        )

    def hooks(self):
        return json.loads((self.agents / "hooks.json").read_text(encoding="utf-8"))


class TestEinrichten(AntigravitySetupTestCase):
    def test_legt_alles_an(self):
        ergebnis = self.setup_ag()
        self.assertErfolg(ergebnis)

        self.assertTrue((self.agents / "hooks.json").is_file())
        self.assertTrue((self.agents / "rules" / "team-sync.md").is_file())
        for name in ("team", "ask", "answer", "decide", "sync"):
            self.assertTrue(
                (self.agents / "workflows" / f"{name}.md").is_file(),
                f"Workflow {name} fehlt",
            )

    def test_alle_ereignisse_eingetragen(self):
        self.assertErfolg(self.setup_ag())
        gruppe = self.hooks()["team-sync"]
        self.assertEqual(
            set(gruppe),
            {"PreInvocation", "PostInvocation", "Stop", "PreToolUse", "PostToolUse"},
        )

    def test_befehle_zeigen_auf_vorhandene_skripte(self):
        """
        Antigravity ersetzt keine Platzhalter. Steht in der hooks.json
        ein Pfad, der ins Leere zeigt, schweigt der Hook einfach, und
        niemand merkt es.
        """
        self.assertErfolg(self.setup_ag())
        gefunden = 0
        for eintraege in self.hooks()["team-sync"].values():
            for eintrag in eintraege:
                for hook in eintrag["hooks"]:
                    befehl = hook["command"]
                    self.assertNotIn("${", befehl, "Platzhalter im Befehl")
                    pfad = Path(befehl.split('"')[1])
                    self.assertTrue(pfad.is_absolute(), befehl)
                    self.assertTrue(pfad.is_file(), f"{pfad} gibt es nicht")
                    self.assertIn("timeout", hook)
                    gefunden += 1
        self.assertEqual(gefunden, 5)

    def test_platzhalter_in_regeln_ersetzt(self):
        self.assertErfolg(self.setup_ag())
        for pfad in list((self.agents / "rules").glob("*.md")) + list(
            (self.agents / "workflows").glob("*.md")
        ):
            text = pfad.read_text(encoding="utf-8")
            self.assertNotIn("{{TEAM_SYNC_ROOT}}", text, pfad.name)
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", text, pfad.name)
            self.assertIn("team_sync.py", text, pfad.name)

    def test_eigener_python_befehl(self):
        self.assertErfolg(self.setup_ag("--python", "py -3"))
        befehl = self.hooks()["team-sync"]["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(befehl.startswith("py -3 "), befehl)

    def test_probelauf_schreibt_nichts(self):
        ergebnis = self.setup_ag("--dry-run")
        self.assertErfolg(ergebnis)
        self.assertIn("würde schreiben", ergebnis.stdout)
        self.assertFalse(self.agents.exists())

    def test_anderer_zielordner(self):
        ziel = self.basis / "woanders"
        ziel.mkdir()
        self.assertErfolg(self.setup_ag("--dir", str(ziel)))
        self.assertTrue((ziel / ".agents" / "hooks.json").is_file())

    def test_zweimal_ausfuehren_bleibt_gleich(self):
        self.assertErfolg(self.setup_ag())
        erst = (self.agents / "hooks.json").read_text(encoding="utf-8")
        self.assertErfolg(self.setup_ag())
        self.assertEqual(erst, (self.agents / "hooks.json").read_text(encoding="utf-8"))


class TestFremdeKonfiguration(AntigravitySetupTestCase):
    def _fremde_hooks_anlegen(self):
        self.agents.mkdir(parents=True, exist_ok=True)
        (self.agents / "hooks.json").write_text(
            json.dumps(FREMDE_GRUPPE, indent=2), encoding="utf-8"
        )

    def test_fremde_gruppe_bleibt_stehen(self):
        self._fremde_hooks_anlegen()
        self.assertErfolg(self.setup_ag())

        daten = self.hooks()
        self.assertIn("mein-linter", daten)
        self.assertEqual(daten["mein-linter"], FREMDE_GRUPPE["mein-linter"])
        self.assertIn("team-sync", daten)

    def test_sicherung_wird_angelegt(self):
        self._fremde_hooks_anlegen()
        self.assertErfolg(self.setup_ag())

        sicherung = self.agents / "hooks.json.team-sync-backup"
        self.assertTrue(sicherung.is_file())
        self.assertEqual(json.loads(sicherung.read_text(encoding="utf-8")), FREMDE_GRUPPE)

    def test_kaputte_datei_wird_nicht_ueberschrieben(self):
        self.agents.mkdir(parents=True, exist_ok=True)
        kaputt = "{ das ist kein JSON"
        (self.agents / "hooks.json").write_text(kaputt, encoding="utf-8")

        ergebnis = self.setup_ag()
        self.assertEqual(ergebnis.returncode, 1)
        self.assertEqual(
            (self.agents / "hooks.json").read_text(encoding="utf-8"), kaputt
        )


class TestEntfernen(AntigravitySetupTestCase):
    def test_nimmt_nur_das_eigene_heraus(self):
        self.agents.mkdir(parents=True, exist_ok=True)
        (self.agents / "hooks.json").write_text(
            json.dumps(FREMDE_GRUPPE, indent=2), encoding="utf-8"
        )
        self.assertErfolg(self.setup_ag())
        self.assertErfolg(self.setup_ag("--entfernen"))

        daten = self.hooks()
        self.assertNotIn("team-sync", daten)
        self.assertIn("mein-linter", daten)
        self.assertFalse((self.agents / "workflows" / "team.md").exists())
        self.assertFalse((self.agents / "rules" / "team-sync.md").exists())

    def test_entfernen_ohne_vorheriges_setup(self):
        ergebnis = self.setup_ag("--entfernen")
        self.assertErfolg(ergebnis)


class TestDoctor(AntigravitySetupTestCase):
    def test_meldet_fehlende_einrichtung_ohne_fehler(self):
        self.team.setup("Anna")
        ergebnis = self.team.cli("Anna", "doctor")
        self.assertErfolg(ergebnis)
        self.assertIn("Antigravity", ergebnis.stdout)
        self.assertIn("nicht eingerichtet", ergebnis.stdout)

    def test_meldet_vorhandene_einrichtung(self):
        self.team.setup("Anna")
        self.assertErfolg(self.setup_ag())

        ergebnis = self.team.cli("Anna", "doctor")
        self.assertErfolg(ergebnis)
        self.assertIn("PreInvocation", ergebnis.stdout)

    def test_zeigt_auf_nichts_ist_ein_problem(self):
        """
        Nach einem Verschieben des Plugins zeigen die absoluten Pfade
        ins Leere. Der Hook schweigt dann, deshalb muss doctor es sagen.
        """
        self.team.setup("Anna")
        self.assertErfolg(self.setup_ag())

        daten = self.hooks()
        daten["team-sync"]["Stop"][0]["hooks"][0]["command"] = (
            'python3 "/gibt/es/nicht/antigravity_hook.py" stop'
        )
        (self.agents / "hooks.json").write_text(
            json.dumps(daten, indent=2), encoding="utf-8"
        )

        ergebnis = self.team.cli("Anna", "doctor")
        self.assertEqual(ergebnis.returncode, 1)
        self.assertIn("/gibt/es/nicht/antigravity_hook.py", ergebnis.stdout)


if __name__ == "__main__":
    unittest.main()
