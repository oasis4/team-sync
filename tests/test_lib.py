"""Tests der reinen Hilfsfunktionen, ohne git."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib import frontmatter
from lib.channel import describe_age, parse_stamp, slugify
from lib.transcript import summarize


class TestSlugify(unittest.TestCase):
    def test_umlaute_werden_ausgeschrieben(self):
        # Der erste Entwurf hatte hier text.replace("ae", "ae"), also
        # gar keine Ersetzung. Aus "Jörg Müller" wurde "j-rg-m-ller",
        # und damit ein Dateiname, der zu keinem Namen mehr passt.
        self.assertEqual(slugify("Jörg Müller"), "joerg-mueller")
        self.assertEqual(slugify("Käthe Schößer"), "kaethe-schoesser")
        self.assertEqual(slugify("ÄÖÜ"), "aeoeue")

    def test_akzente_werden_transliteriert(self):
        self.assertEqual(slugify("Renée Dupont"), "renee-dupont")
        self.assertEqual(slugify("Łukasz"), "ukasz")

    def test_gleicher_name_gleicher_slug(self):
        self.assertEqual(slugify("Max Mustermann"), slugify("max mustermann"))
        self.assertEqual(slugify("  Max  Mustermann  "), "max-mustermann")

    def test_leere_eingabe(self):
        self.assertEqual(slugify(""), "unbekannt")
        self.assertEqual(slugify("!!!"), "unbekannt")
        self.assertEqual(slugify(None), "unbekannt")


class TestFrontmatter(unittest.TestCase):
    def test_hin_und_zurueck(self):
        text = frontmatter.build(
            {"typ": "frage", "an": "max", "status": "offen"}, "# Titel\n\nInhalt"
        )
        felder, rumpf = frontmatter.parse(text)
        self.assertEqual(felder["typ"], "frage")
        self.assertEqual(felder["an"], "max")
        self.assertIn("Inhalt", rumpf)

    def test_ohne_frontmatter(self):
        felder, rumpf = frontmatter.parse("Nur Text\n")
        self.assertEqual(felder, {})
        self.assertEqual(rumpf, "Nur Text\n")

    def test_trennlinie_im_rumpf_beendet_den_kopf_nicht(self):
        text = frontmatter.build({"typ": "frage"}, "Oben\n\n---\n\nUnten")
        felder, rumpf = frontmatter.parse(text)
        self.assertEqual(felder["typ"], "frage")
        self.assertIn("Oben", rumpf)
        self.assertIn("Unten", rumpf)

    def test_zeilenumbruch_im_feldwert_zerstoert_den_kopf_nicht(self):
        text = frontmatter.build({"titel": "erste Zeile\nzweite Zeile"}, "Rumpf")
        felder, rumpf = frontmatter.parse(text)
        self.assertEqual(felder["titel"], "erste Zeile zweite Zeile")
        self.assertEqual(rumpf.strip(), "Rumpf")

    def test_werte_mit_doppelpunkt(self):
        text = frontmatter.build({"titel": "Auth: JWT statt Session"}, "x")
        felder, _ = frontmatter.parse(text)
        self.assertEqual(felder["titel"], "Auth: JWT statt Session")

    def test_person_erkennen(self):
        self.assertTrue(frontmatter.matches_person("max", "Max"))
        self.assertTrue(frontmatter.matches_person("Max Mustermann", "max-mustermann"))
        self.assertTrue(frontmatter.matches_person("lars, max", "max"))
        self.assertFalse(frontmatter.matches_person("maxine", "max"))
        self.assertFalse(frontmatter.matches_person("", "max"))


class TestTranskript(unittest.TestCase):
    """
    Die Auswertung muss technisches Rauschen aussortieren. Landet es im
    Status, liest das Team statt einer Arbeitsbeschreibung eine
    Werkzeugausgabe.
    """

    def _schreibe(self, eintraege):
        import json
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for eintrag in eintraege:
            handle.write(json.dumps(eintrag) + "\n")
        handle.close()
        return handle.name

    def test_auftrag_und_letzte_nachricht(self):
        pfad = self._schreibe([
            {"type": "user", "message": {"content": "Bau die Anmeldung um"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "auth.py"}}
            ]}},
            {"type": "user", "message": {"content": "ja, weiter"}},
        ])
        ergebnis = summarize(pfad)
        self.assertEqual(ergebnis["auftrag"], "Bau die Anmeldung um")
        self.assertEqual(ergebnis["zuletzt"], "ja, weiter")
        self.assertEqual(ergebnis["dateien"], ["auth.py"])

    def test_werkzeugausgaben_zaehlen_nicht_als_nutzertext(self):
        pfad = self._schreibe([
            {"type": "user", "message": {"content": "Der eigentliche Auftrag"}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "1200 Zeilen Testausgabe"}
            ]}},
        ])
        ergebnis = summarize(pfad)
        self.assertEqual(ergebnis["auftrag"], "Der eigentliche Auftrag")
        self.assertNotIn("Testausgabe", ergebnis["zuletzt"])

    def test_system_reminder_wird_entfernt(self):
        pfad = self._schreibe([
            {"type": "user", "message": {"content":
                "Baue X um<system-reminder>Interner Hinweis</system-reminder>"}},
        ])
        ergebnis = summarize(pfad)
        self.assertEqual(ergebnis["auftrag"], "Baue X um")

    def test_reine_meta_nachricht_wird_uebersprungen(self):
        pfad = self._schreibe([
            {"type": "user", "message": {"content":
                "<system-reminder>nur Rauschen</system-reminder>"}},
            {"type": "user", "message": {"content": "Echter Auftrag"}},
        ])
        self.assertEqual(summarize(pfad)["auftrag"], "Echter Auftrag")

    def test_nur_bearbeitende_werkzeuge_zaehlen(self):
        pfad = self._schreibe([
            {"type": "user", "message": {"content": "Auftrag"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "nur_gelesen.py"}},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "geschrieben.py"}},
            ]}},
        ])
        self.assertEqual(summarize(pfad)["dateien"], ["geschrieben.py"])

    def test_kaputte_zeilen_brechen_nichts_ab(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        handle.write('{"type": "user", "message": {"content": "Auftrag"}}\n')
        handle.write("kein json\n")
        handle.write("\n")
        handle.close()
        self.assertEqual(summarize(handle.name)["auftrag"], "Auftrag")

    def test_fehlendes_transkript(self):
        ergebnis = summarize("/gibt/es/nicht.jsonl")
        self.assertEqual(ergebnis["auftrag"], "")
        self.assertEqual(ergebnis["dateien"], [])
        self.assertEqual(summarize("")["auftrag"], "")


class TestZeit(unittest.TestCase):
    def test_stempel_lesen(self):
        self.assertIsNotNone(parse_stamp("2026-08-16 18:30"))
        self.assertIsNotNone(parse_stamp("2026-08-16"))
        self.assertIsNone(parse_stamp("neulich"))
        self.assertIsNone(parse_stamp(""))

    def test_alter_beschreiben(self):
        from datetime import datetime, timedelta

        vor_drei_stunden = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(describe_age(vor_drei_stunden), "vor 3 Stunden")

        vor_zwei_tagen = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(describe_age(vor_zwei_tagen), "vor 2 Tagen")

        self.assertEqual(describe_age("unlesbar"), "")


if __name__ == "__main__":
    unittest.main()
