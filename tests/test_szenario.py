"""
Der ganze Ablauf zweier Teammitglieder als Test, siehe tests/szenario.py.

Ein einzelner langer Test statt vieler kleiner, weil es genau um das
Zusammenspiel geht: Ein Schritt funktioniert nur, wenn der davor
wirklich bei der anderen Session angekommen ist.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import szenario


@unittest.skipIf(
    os.name == "nt" or not all(shutil.which(b) for b in ("bash", "sh", "pgrep")),
    "Das Szenario braucht bash, sh und pgrep",
)
class TestSzenario(unittest.TestCase):
    def test_zwei_sessions_stimmen_sich_ab(self):
        zeilen = []
        with tempfile.TemporaryDirectory(prefix="team-sync-szenario-") as tmp:
            ergebnisse = szenario.ablauf(Path(tmp).resolve(), ausgabe=zeilen.append)
        fehlt = [schritt for schritt, ok, _ in ergebnisse if not ok]
        self.assertFalse(fehlt, "\n".join(["Fehlende Schritte:"] + fehlt + ["", "Verlauf:"] + zeilen))
        self.assertGreaterEqual(len(ergebnisse), 15)


if __name__ == "__main__":
    unittest.main()
