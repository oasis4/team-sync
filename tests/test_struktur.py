"""
Prüft die Plugin-Struktur selbst.

Diese Fehler tun besonders weh, weil sie nicht knallen: Ein Plugin mit
einem falschen Namen in einer der beiden JSON-Dateien installiert sich
scheinbar, nur passiert danach nichts. Ein Hook, der auf ein
umbenanntes Skript zeigt, schweigt einfach. Deshalb hier geprüft statt
im Alltag entdeckt.
"""

import json
import re
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
HOOK_EREIGNISSE = {
    "SessionStart", "Stop", "SessionEnd", "PreToolUse", "PostToolUse",
}

# Hooks, die vor bzw. nach jedem einzelnen Werkzeugaufruf laufen und
# deshalb einen Filter brauchen. Ohne matcher liefen sie auch bei jedem
# Read und jedem Bash-Aufruf mit.
BRAUCHEN_MATCHER = {"PreToolUse", "PostToolUse"}


def lies_json(pfad: Path):
    return json.loads(pfad.read_text(encoding="utf-8"))


class TestManifeste(unittest.TestCase):
    def setUp(self):
        self.plugin = lies_json(WURZEL / ".claude-plugin" / "plugin.json")
        self.marketplace = lies_json(WURZEL / ".claude-plugin" / "marketplace.json")

    def test_name_ist_ueberall_gleich(self):
        """
        Der Name muss in plugin.json, marketplace.json und im
        Repositoriumsnamen übereinstimmen, sonst findet
        '/plugin install' das Plugin nicht.
        """
        eintraege = self.marketplace["plugins"]
        namen = {eintrag["name"] for eintrag in eintraege}
        self.assertIn(self.plugin["name"], namen)
        self.assertEqual(self.plugin["name"], WURZEL.name)

    def test_version_ist_semver(self):
        self.assertRegex(self.plugin["version"], r"^\d+\.\d+\.\d+$")

    def test_version_steht_im_changelog(self):
        changelog = (WURZEL / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"[{self.plugin['version']}]", changelog)

    def test_pflichtfelder(self):
        for feld in ("name", "version", "description", "license"):
            self.assertIn(feld, self.plugin, f"plugin.json fehlt: {feld}")

    def test_quelle_im_marketplace_existiert(self):
        for eintrag in self.marketplace["plugins"]:
            quelle = eintrag["source"]
            self.assertTrue(quelle.startswith("./"), f"Pfad muss relativ sein: {quelle}")
            self.assertTrue((WURZEL / quelle).is_dir())


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.hooks = lies_json(WURZEL / "hooks" / "hooks.json")["hooks"]

    def test_erwartete_ereignisse(self):
        self.assertEqual(set(self.hooks), HOOK_EREIGNISSE)

    def test_verwiesene_skripte_existieren(self):
        for ereignis, gruppen in self.hooks.items():
            for gruppe in gruppen:
                for hook in gruppe["hooks"]:
                    befehl = hook["command"]
                    treffer = re.search(r"scripts/([\w_]+\.py)", befehl)
                    self.assertIsNotNone(treffer, f"{ereignis}: {befehl}")
                    skript = WURZEL / "scripts" / treffer.group(1)
                    self.assertTrue(skript.is_file(), f"{ereignis} zeigt auf {skript}")

    def test_pluginwurzel_wird_verwendet(self):
        """
        Ein Hook darf keinen absoluten Pfad enthalten. Er läuft auf dem
        Rechner jedes Teammitglieds, und dort liegt das Plugin woanders.
        """
        for gruppen in self.hooks.values():
            for gruppe in gruppen:
                for hook in gruppe["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", hook["command"])

    def test_werkzeug_hooks_haben_matcher(self):
        for ereignis in BRAUCHEN_MATCHER:
            for gruppe in self.hooks[ereignis]:
                self.assertIn("matcher", gruppe, f"{ereignis} ohne matcher")
                self.assertIn("Edit", gruppe["matcher"])

    def test_timeouts_gesetzt(self):
        for ereignis, gruppen in self.hooks.items():
            for gruppe in gruppen:
                for hook in gruppe["hooks"]:
                    self.assertIn("timeout", hook, f"{ereignis} ohne Timeout")
                    self.assertLessEqual(hook["timeout"], 60)


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.dateien = sorted((WURZEL / "commands").glob("*.md"))

    def test_commands_vorhanden(self):
        namen = {pfad.stem for pfad in self.dateien}
        self.assertEqual(namen, {"ask", "answer", "decide", "sync", "team"})

    def test_frontmatter_vollstaendig(self):
        for pfad in self.dateien:
            text = pfad.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"{pfad.name} ohne Frontmatter")
            kopf = text.split("---", 2)[1]
            self.assertIn("description:", kopf, f"{pfad.name} ohne description")
            self.assertIn("name:", kopf, f"{pfad.name} ohne name")

    def test_name_passt_zum_dateinamen(self):
        for pfad in self.dateien:
            kopf = pfad.read_text(encoding="utf-8").split("---", 2)[1]
            treffer = re.search(r"^name:\s*(\S+)", kopf, re.MULTILINE)
            self.assertEqual(treffer.group(1), pfad.stem)

    def test_commands_rufen_die_kommandozeile_auf(self):
        """
        Ein Command, der wieder anfängt, git-Befehle zu beschreiben,
        gehört ins Skript. Nur /team und /answer dürfen lesen, ohne zu
        schreiben, aber auch sie gehen über team_sync.py.
        """
        for pfad in self.dateien:
            text = pfad.read_text(encoding="utf-8")
            self.assertIn("team_sync.py", text, f"{pfad.name} ruft die CLI nicht auf")
            self.assertNotIn(
                "git commit",
                text,
                f"{pfad.name} beschreibt git-Aufrufe, die ins Skript gehören",
            )


class TestAntigravity(unittest.TestCase):
    """
    Die Antigravity-Seite des Plugins.

    Sie hat kein eigenes Manifest, das ein Programm prüfen würde. Fehlt
    hier eine Datei oder bleibt ein Platzhalter stehen, fällt das erst
    dem Teammitglied auf, das damit arbeitet, und dann in Form eines
    Hooks, der nichts tut.
    """

    def setUp(self):
        self.regeln = sorted((WURZEL / "antigravity" / "rules").glob("*.md"))
        self.workflows = sorted((WURZEL / "antigravity" / "workflows").glob("*.md"))

    def test_regeln_vorhanden(self):
        self.assertTrue(self.regeln, "antigravity/rules ist leer")

    def test_workflows_decken_die_commands_ab(self):
        """
        Wer mit Antigravity arbeitet, soll dieselben fünf Befehle haben
        wie alle anderen. Ein fehlender Workflow heißt: Diese Person
        kann etwas nicht, was das Team von ihr erwartet.
        """
        commands = {pfad.stem for pfad in (WURZEL / "commands").glob("*.md")}
        self.assertEqual({pfad.stem for pfad in self.workflows}, commands)

    def test_frontmatter_vorhanden(self):
        for pfad in self.regeln + self.workflows:
            text = pfad.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"{pfad.name} ohne Frontmatter")
            kopf = text.split("---", 2)[1]
            self.assertIn("description:", kopf, f"{pfad.name} ohne description")

    def test_platzhalter_statt_claude_variable(self):
        """
        Antigravity ersetzt ${CLAUDE_PLUGIN_ROOT} nicht. Stünde das hier,
        bekäme das Modell einen Befehl, den keine Shell auflösen kann.
        """
        for pfad in self.regeln + self.workflows:
            text = pfad.read_text(encoding="utf-8")
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", text, pfad.name)
            self.assertIn("{{TEAM_SYNC_ROOT}}", text, f"{pfad.name} ohne Platzhalter")

    def test_workflows_rufen_die_kommandozeile_auf(self):
        for pfad in self.workflows:
            text = pfad.read_text(encoding="utf-8")
            self.assertIn("team_sync.py", text, f"{pfad.name} ruft die CLI nicht auf")
            self.assertNotIn("git commit", text, f"{pfad.name} beschreibt git-Aufrufe")

    def test_setup_skript_vorhanden(self):
        self.assertTrue((WURZEL / "scripts" / "setup_antigravity.py").is_file())
        self.assertTrue((WURZEL / "scripts" / "antigravity_hook.py").is_file())

    def test_ereignisse_des_einstiegspunkts(self):
        """
        Das Skript und das Setup müssen sich über die Argumente einig
        sein. Ein Tippfehler hier ergibt einen Hook, der bei jedem
        Aufruf mit Code 1 aussteigt, ohne dass es jemandem auffällt.
        """
        import sys as _sys

        _sys.path.insert(0, str(WURZEL / "scripts"))
        import antigravity_hook
        import setup_antigravity

        gruppe = setup_antigravity.hooks_bauen("python3")
        self.assertEqual(set(gruppe), set(antigravity_hook.EREIGNISSE.values()) | {
            "PreToolUse", "PostToolUse"
        })

        for ereignisname, eintraege in gruppe.items():
            for eintrag in eintraege:
                for hook in eintrag["hooks"]:
                    befehl = hook["command"]
                    if "antigravity_hook.py" not in befehl:
                        continue
                    argument = befehl.rsplit('"', 1)[-1].strip()
                    self.assertIn(
                        argument, antigravity_hook.EREIGNISSE,
                        f"{ereignisname}: unbekanntes Argument '{argument}'",
                    )


class TestSkripte(unittest.TestCase):
    def test_alle_skripte_uebersetzen(self):
        import py_compile

        for pfad in sorted((WURZEL / "scripts").rglob("*.py")):
            try:
                py_compile.compile(str(pfad), doraise=True, cfile=None)
            except py_compile.PyCompileError as fehler:
                self.fail(f"{pfad.name}: {fehler}")

    def test_keine_zu_neue_standardbibliothek(self):
        """
        Im Team laufen unterschiedliche Python-Versionen. Path.write_text
        mit newline= gibt es erst ab 3.10 und ist beim Setup unter 3.9
        mit einem TypeError ausgestiegen, obwohl es hier unter 3.13
        durchlief. Dafür gibt es write_text_lf in lib/channel.py.
        """
        verboten = (
            (r"write_text\([^)]*newline", "Path.write_text(newline=) braucht 3.10"),
            (r"\bremoveprefix\(|\bremovesuffix\(", "str.removeprefix braucht 3.9"),
            (r"zip\([^)]*strict=", "zip(strict=) braucht 3.10"),
        )
        for pfad in sorted((WURZEL / "scripts").rglob("*.py")):
            text = pfad.read_text(encoding="utf-8")
            # Die eigene Hilfsfunktion darf open(newline=) verwenden.
            text = text.replace('open(str(path), "w", encoding="utf-8", newline="\\n")', "")
            for muster, grund in verboten:
                treffer = re.search(muster, text)
                self.assertIsNone(treffer, f"{pfad.name}: {grund}")

    def test_mindestversion_ist_dokumentiert(self):
        readme = (WURZEL / "README.md").read_text(encoding="utf-8")
        ci = (WURZEL / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        version = re.search(r"Python (\d+\.\d+) oder neuer", readme)
        self.assertIsNotNone(version, "README nennt keine Mindestversion")
        self.assertIn(
            f'"{version.group(1)}"', ci,
            "Die im README genannte Mindestversion wird von der CI nicht getestet",
        )

    def test_keine_externen_abhaengigkeiten(self):
        """
        Das Plugin muss ohne pip install laufen. Ein versehentlicher
        Import von requests oder yaml würde es auf einem fremden
        Rechner stillschweigend lahmlegen.
        """
        erlaubt = {
            "argparse", "json", "os", "re", "subprocess", "sys", "time",
            "unicodedata", "datetime", "pathlib", "lib", "collections",
            "shutil", "tempfile", "textwrap", "typing", "py_compile",
        }
        muster = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][\w]*)", re.MULTILINE)

        for pfad in sorted((WURZEL / "scripts").rglob("*.py")):
            text = pfad.read_text(encoding="utf-8")
            for modul in muster.findall(text):
                if modul.startswith("."):
                    continue
                self.assertIn(
                    modul, erlaubt,
                    f"{pfad.name} importiert '{modul}', das nicht zur "
                    f"Standardbibliothek gehört oder hier nicht vorgesehen ist",
                )


class TestDokumentation(unittest.TestCase):
    def test_dateien_vorhanden(self):
        for name in ("README.md", "LICENSE", "CONTRIBUTING.md", "CHANGELOG.md",
                     ".gitignore"):
            self.assertTrue((WURZEL / name).is_file(), f"{name} fehlt")

    def test_readme_nennt_antigravity(self):
        """
        Ein zweites Hostprogramm, das nirgends steht, benutzt niemand.
        """
        readme = (WURZEL / "README.md").read_text(encoding="utf-8")
        self.assertIn("Antigravity", readme)
        self.assertIn("setup_antigravity.py", readme)

    def test_readme_nennt_alle_commands(self):
        readme = (WURZEL / "README.md").read_text(encoding="utf-8")
        for pfad in (WURZEL / "commands").glob("*.md"):
            self.assertIn(f"/{pfad.stem}", readme, f"README nennt /{pfad.stem} nicht")

    def test_readme_nennt_die_einstellungen(self):
        """
        Eine Stellschraube, die niemand kennt, ist keine Stellschraube.
        Geprüft wird über alle Module, nicht nur über channel.py.
        """
        readme = (WURZEL / "README.md").read_text(encoding="utf-8")
        for pfad in sorted((WURZEL / "scripts").rglob("*.py")):
            quelle = pfad.read_text(encoding="utf-8")
            for variable in re.findall(r'environ\.get\(\s*"(TEAM_[A-Z_]+)"', quelle):
                # assertTrue statt assertIn: Sonst kippt unittest bei
                # einem Fehlschlag die komplette README in die Ausgabe.
                self.assertTrue(
                    variable in readme,
                    f"README erklärt {variable} nicht (aus {pfad.name})",
                )


if __name__ == "__main__":
    unittest.main()
