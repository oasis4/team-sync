"""
Testumgebung: ein echtes kleines Team.

Baut ein bare Repository als Remote und dazu beliebig viele Klone, je
einer pro erfundenem Teammitglied. Die Tests laufen dann gegen echte
git-Kommandos statt gegen Attrappen.

Das ist Absicht. Fast alles, was an diesem Plugin schiefgehen kann,
passiert in git: ein Worktree, der nicht gefunden wird, ein Push, der
abgelehnt wird, weil jemand schneller war, ein Branch, der auf einer
älteren git-Version anders angelegt werden muss. Nachgebaute
git-Antworten würden genau diese Fälle bestätigen statt prüfen.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts"


def git(args, cwd, input_text=None, check=True):
    ergebnis = subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
    )
    if check and ergebnis.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} in {cwd} fehlgeschlagen:\n{ergebnis.stderr}"
        )
    return ergebnis


class TeamUmgebung:
    """Ein Remote, mehrere Arbeitskopien, je eine pro Person."""

    def __init__(self, basis: Path):
        self.basis = basis
        self.remote = basis / "remote.git"
        self.projekte = {}
        self.channels = {}

        git(["init", "--bare", "-b", "main", str(self.remote)], cwd=basis)

    def person_anlegen(self, name: str, ordner=None) -> Path:
        ordner = ordner or name
        ziel = self.basis / ordner
        git(["clone", str(self.remote), str(ziel)], cwd=self.basis)
        git(["config", "user.name", name], cwd=ziel)
        git(["config", "user.email", f"{name.lower()}@example.test"], cwd=ziel)
        git(["config", "commit.gpgsign", "false"], cwd=ziel)

        if not (ziel / "README.md").exists() and not self._hat_commits(ziel):
            (ziel / "README.md").write_text("# Testprojekt\n", encoding="utf-8")
            git(["add", "-A"], cwd=ziel)
            git(["commit", "-m", "erster Commit"], cwd=ziel)
            git(["push", "-u", "origin", "main"], cwd=ziel)

        self.projekte[name] = ziel
        self.channels[name] = self.basis / f"{ordner}-channel"
        return ziel

    @staticmethod
    def _hat_commits(repo: Path) -> bool:
        return git(["rev-parse", "HEAD"], cwd=repo, check=False).returncode == 0

    def umgebung(self, name: str, extra=None):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.projekte[name])
        env["TEAM_AGENT_NAME"] = name
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        # Sonst schlagen Commits in den Testrepos an fehlender Identität fehl.
        env["GIT_AUTHOR_NAME"] = name
        env["GIT_AUTHOR_EMAIL"] = f"{name.lower()}@example.test"
        env["GIT_COMMITTER_NAME"] = name
        env["GIT_COMMITTER_EMAIL"] = f"{name.lower()}@example.test"
        env.pop("TEAM_SYNC_CHANNEL_DIR", None)
        if extra:
            env.update(extra)
        return env

    def setup(self, name: str, extra=None):
        """Führt setup_channel.py so aus, wie es ein Teammitglied täte."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "setup_channel.py")],
            cwd=str(self.projekte[name]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.umgebung(name, extra),
        )

    def cli(self, name: str, *args, extra=None, stdin=None):
        """Ruft team_sync.py auf."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "team_sync.py")] + [str(a) for a in args],
            cwd=str(self.projekte[name]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=stdin,
            env=self.umgebung(name, extra),
        )

    def hook(self, name: str, skript: str, payload=None, extra=None):
        """Ruft ein Hook-Skript mit einer Payload auf, wie Claude Code es tut."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS / skript)],
            cwd=str(self.projekte[name]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=json.dumps(payload or {}),
            env=self.umgebung(name, extra),
        )

    def umgebung_antigravity(self, name: str, extra=None):
        """
        Wie umgebung(), aber ohne die Claude-Code-Variablen.

        Unter Antigravity gibt es weder CLAUDE_PROJECT_DIR noch
        CLAUDE_PLUGIN_ROOT. Genau das ist der Fall, den die Hooks
        überstehen müssen: Der Projektordner steht nur in der Nutzlast.
        """
        env = self.umgebung(name, extra)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        env.pop("TEAM_SYNC_PROJECT_DIR", None)
        env.pop("TEAM_SYNC_HOST", None)
        if extra:
            env.update(extra)
        return env

    def ag_hook(self, name: str, skript: str, payload=None, argv=(), extra=None):
        """Ruft ein Hook-Skript so auf, wie Antigravity es tut."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS / skript)] + [str(a) for a in argv],
            cwd=str(self.basis),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=json.dumps(payload or {}),
            env=self.umgebung_antigravity(name, extra),
        )

    def ag_werkzeug(self, name: str, datei, werkzeug="write_to_file", unterhaltung="c1"):
        """Nutzlast eines Werkzeugaufrufs im Antigravity-Format."""
        return {
            "conversationId": unterhaltung,
            "workspacePaths": [str(self.projekte[name])],
            "stepIdx": 1,
            "toolCall": {"name": werkzeug, "args": {"file_path": str(datei)}},
        }

    def ag_invocation(self, name: str, transkript="", unterhaltung="c1"):
        """Nutzlast von PreInvocation, PostInvocation und Stop."""
        return {
            "conversationId": unterhaltung,
            "workspacePaths": [str(self.projekte[name])],
            "transcriptPath": str(transkript),
        }

    def ag_transkript_schreiben(self, name: str, eintraege) -> Path:
        """
        Legt ein Transkript im fremden Format an.

        Bewusst nicht das Claude-Code-Schema, denn geprüft werden soll
        gerade der nachgiebige Weg in lib/transcript.py.
        """
        pfad = self.basis / f"ag-transcript-{name}.jsonl"
        with pfad.open("w", encoding="utf-8") as handle:
            for eintrag in eintraege:
                handle.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        return pfad

    def channel_datei(self, name: str, relativ: str) -> Path:
        return self.channels[name] / relativ

    def transkript_schreiben(self, name: str, eintraege) -> Path:
        """Legt eine JSONL-Transkriptdatei an, wie Claude Code sie führt."""
        pfad = self.basis / f"transcript-{name}.jsonl"
        with pfad.open("w", encoding="utf-8") as handle:
            for eintrag in eintraege:
                handle.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        return pfad


def nutzer_nachricht(text: str):
    return {"type": "user", "message": {"role": "user", "content": text}}


def werkzeug_aufruf(werkzeug: str, datei: str):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": werkzeug,
                    "input": {"file_path": datei},
                }
            ],
        },
    }


class TeamTestCase(unittest.TestCase):
    """Basisklasse, die pro Test eine frische Umgebung aufbaut."""

    personen = ("Lars", "Max")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="team-sync-test-")
        self.basis = Path(self._tmp.name).resolve()
        self.team = TeamUmgebung(self.basis)
        for person in self.personen:
            self.team.person_anlegen(person)

    def tearDown(self):
        self._tmp.cleanup()

    def setup_alle(self):
        for person in self.personen:
            ergebnis = self.team.setup(person)
            self.assertEqual(
                ergebnis.returncode, 0,
                f"Setup für {person} fehlgeschlagen:\n{ergebnis.stdout}\n{ergebnis.stderr}",
            )

    def assertErfolg(self, ergebnis, hinweis=""):
        self.assertEqual(
            ergebnis.returncode, 0,
            f"{hinweis}\nstdout: {ergebnis.stdout}\nstderr: {ergebnis.stderr}",
        )


def ag_nutzer_nachricht(text: str):
    """Eine Nutzeräußerung, wie ein fremdes Transkript sie schreibt."""
    return {"type": "USER_MESSAGE", "content": text}


def ag_planer_antwort(text: str):
    return {"type": "PLANNER_RESPONSE", "content": text}
