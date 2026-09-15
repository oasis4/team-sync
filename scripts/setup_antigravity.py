#!/usr/bin/env python3
"""
Einmaliges Setup für Antigravity.

Claude Code installiert team-sync als Plugin, damit sind Hooks und
Slash-Commands erledigt. Antigravity kennt dieses Pluginformat nicht, es
liest seine Erweiterungen aus eigenen Dateien. Dieses Skript legt sie
an, im Projekt ausgeführt:

    python3 <team-sync>/scripts/setup_antigravity.py

Geschrieben wird, standardmäßig in den Projektordner:

    .agents/hooks.json          Hooks, verweist auf dieses Repo
    .agents/rules/              Dauerregel zum Team-Channel
    .agents/workflows/          /team, /ask, /answer, /decide, /sync

Mit --global landet dasselbe unter ~/.gemini/config/ und gilt dann für
alle Projekte. Das ist die schlechtere Vorgabe: Die Hooks laufen dann
auch in Repositories ohne Channel. Schaden tun sie dort nicht, sie
steigen ohne Channel sofort wieder aus, aber jeder Modellaufruf kostet
dann einen Prozessstart mehr.

Zwei Dinge, die Antigravity anders macht als Claude Code und die dieses
Skript deshalb überhaupt nötig machen:

1. Platzhalter wie ${CLAUDE_PLUGIN_ROOT} werden nicht ersetzt. In der
   hooks.json müssen absolute Pfade stehen, und die kennt erst der
   Rechner, auf dem installiert wird.
2. Die hooks.json ist nach frei gewählten Gruppen gegliedert, nicht nach
   Ereignissen. Eine vorhandene Datei wird deshalb eingelesen und nur um
   die Gruppe "team-sync" ergänzt, statt überschrieben. Vorher entsteht
   eine Sicherungskopie.

Zum Deinstallieren: --entfernen nimmt die Gruppe wieder heraus und
löscht die angelegten Regeln und Workflows.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.channel import run_git, setup_stdio, write_text_lf

WURZEL = Path(__file__).resolve().parent.parent

# Name der Hook-Gruppe in der hooks.json. Alles unter diesem Schlüssel
# gehört uns, alles daneben gehört jemand anderem und wird nicht
# angefasst.
GRUPPE = "team-sync"

# Platzhalter in den mitgelieferten Regeln und Workflows.
PLATZHALTER = "{{TEAM_SYNC_ROOT}}"

GLOBALER_ORDNER = Path.home() / ".gemini" / "config"


def hooks_bauen(python_befehl: str) -> dict:
    """
    Die Hook-Gruppe für Antigravity.

    Die Zuordnung zu den Ereignissen von Claude Code steht im Kopf von
    scripts/antigravity_hook.py. Kurz:

        PreInvocation    Teamstand beim ersten Zug, danach der Rückkanal
        PostInvocation   gedrosselter Zwischenstand
        Stop             letzter Stand, Reservierungen freigeben
        PreToolUse       Hinweis auf eine belegte Datei
        PostToolUse      Datei beim ersten Zugriff reservieren

    Ohne matcher bei den beiden Werkzeug-Hooks, mit Absicht. Wie die
    schreibenden Werkzeuge in einer bestimmten Antigravity-Version
    heißen, ist nicht festgeschrieben, und ein matcher, der danebenliegt,
    schaltet die Reservierungen stumm ab, ohne dass es auffällt. Die
    Skripte prüfen den Namen deshalb selbst und steigen sofort aus, wenn
    kein Dateipfad im Aufruf steckt. Wer die Namen seiner Installation
    kennt, setzt sie über TEAM_SYNC_AG_EDIT_TOOLS.
    """
    def befehl(*teile):
        skript = WURZEL / "scripts" / teile[0]
        rest = " ".join(teile[1:])
        return f'{python_befehl} "{skript}"' + (f" {rest}" if rest else "")

    return {
        "PreInvocation": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": befehl("antigravity_hook.py", "pre-invocation"),
                        "timeout": 20,
                    }
                ]
            }
        ],
        "PostInvocation": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": befehl("antigravity_hook.py", "post-invocation"),
                        "timeout": 25,
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": befehl("antigravity_hook.py", "stop"),
                        "timeout": 30,
                    }
                ]
            }
        ],
        "PreToolUse": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": befehl("tool_pre_edit.py"),
                        "timeout": 10,
                    }
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": befehl("tool_post_edit.py"),
                        "timeout": 25,
                    }
                ]
            }
        ],
    }


def sichern(pfad: Path):
    """Legt eine Sicherungskopie an, bevor eine fremde Datei geändert wird."""
    if not pfad.is_file():
        return None
    sicherung = pfad.with_suffix(pfad.suffix + ".team-sync-backup")
    if sicherung.exists():
        return sicherung
    try:
        shutil.copy2(str(pfad), str(sicherung))
        return sicherung
    except Exception:
        return None


def hooks_schreiben(ziel: Path, python_befehl: str, entfernen: bool, probelauf: bool):
    """
    Trägt die Gruppe in die hooks.json ein oder nimmt sie heraus.

    Eine kaputte oder unerwartet aufgebaute Datei wird nicht überschrieben.
    Lieber abbrechen und die Person nachsehen lassen, als ihr eine
    Konfiguration zu zerschießen, die mit diesem Plugin nichts zu tun hat.
    """
    vorhanden = {}
    if ziel.is_file():
        try:
            vorhanden = json.loads(ziel.read_text(encoding="utf-8"))
        except Exception as exc:
            print(
                f"  {ziel} ist kein lesbares JSON ({exc}).\n"
                f"  Nichts geändert. Bitte die Datei prüfen oder umbenennen.",
                file=sys.stderr,
            )
            return False
        if not isinstance(vorhanden, dict):
            print(f"  {ziel} hat einen unerwarteten Aufbau. Nichts geändert.", file=sys.stderr)
            return False

    if entfernen:
        if GRUPPE not in vorhanden:
            print(f"  {ziel}: keine Gruppe '{GRUPPE}' eingetragen")
            return True
        vorhanden.pop(GRUPPE)
    else:
        vorhanden[GRUPPE] = hooks_bauen(python_befehl)

    if probelauf:
        print(f"  würde schreiben: {ziel}")
        return True

    sicherung = sichern(ziel)
    if sicherung:
        print(f"  Sicherung: {sicherung}")

    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(ziel, json.dumps(vorhanden, indent=2, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"  {ziel} konnte nicht geschrieben werden: {exc}", file=sys.stderr)
        return False

    print(f"  geschrieben: {ziel}")
    return True


def texte_schreiben(quelle: Path, ziel: Path, entfernen: bool, probelauf: bool):
    """Kopiert Regeln und Workflows und setzt den Pfad zum Plugin ein."""
    if not quelle.is_dir():
        return True

    erfolg = True
    for datei in sorted(quelle.glob("*.md")):
        zieldatei = ziel / datei.name

        if entfernen:
            if probelauf:
                print(f"  würde löschen: {zieldatei}")
                continue
            try:
                zieldatei.unlink()
                print(f"  gelöscht: {zieldatei}")
            except FileNotFoundError:
                pass
            except Exception as exc:
                print(f"  {zieldatei} konnte nicht gelöscht werden: {exc}", file=sys.stderr)
                erfolg = False
            continue

        inhalt = datei.read_text(encoding="utf-8").replace(
            PLATZHALTER, str(WURZEL).replace("\\", "/")
        )

        if probelauf:
            print(f"  würde schreiben: {zieldatei}")
            continue

        try:
            ziel.mkdir(parents=True, exist_ok=True)
            write_text_lf(zieldatei, inhalt)
            print(f"  geschrieben: {zieldatei}")
        except Exception as exc:
            print(f"  {zieldatei} konnte nicht geschrieben werden: {exc}", file=sys.stderr)
            erfolg = False

    return erfolg


def _gitignore_hinweis(ziel: Path):
    """
    Erinnert daran, den .agents-Ordner nicht mitzucommitten.

    In den geschriebenen Dateien stehen absolute Pfade zu diesem Klon.
    Landen sie im Repository, zeigen sie auf dem Rechner der nächsten
    Person ins Leere, und ihre Hooks tun still nichts. Das ist genau die
    Sorte Fehler, die niemand sucht, weil nichts knallt.

    Nur ein Hinweis. Die .gitignore gehört dem Projekt, nicht uns.
    """
    if ziel.name != ".agents":
        return

    projekt = ziel.parent
    gitignore = projekt / ".gitignore"
    try:
        if gitignore.is_file():
            zeilen = {
                zeile.strip().rstrip("/")
                for zeile in gitignore.read_text(encoding="utf-8").splitlines()
            }
            if ".agents" in zeilen:
                return
    except Exception:
        return

    print()
    print("Hinweis: In den Dateien stehen absolute Pfade zu diesem Klon.")
    print("Sie gehören nicht ins Repository. Einmal eintragen:")
    print(f'  echo ".agents/" >> "{gitignore}"')


def main() -> int:
    setup_stdio()

    parser = argparse.ArgumentParser(
        description="team-sync in Antigravity einrichten",
    )
    parser.add_argument(
        "--global", dest="global_", action="store_true",
        help="Nach ~/.gemini/config statt in den Projektordner schreiben",
    )
    parser.add_argument(
        "--dir", help="Anderer Zielordner für .agents (Vorgabe: Projektwurzel)",
    )
    parser.add_argument(
        "--python", default="python3",
        help="Befehl für Python in den Hooks (Vorgabe: python3)",
    )
    parser.add_argument(
        "--entfernen", action="store_true",
        help="Eintrag wieder herausnehmen",
    )
    parser.add_argument(
        "--dry-run", dest="probelauf", action="store_true",
        help="Nur zeigen, was passieren würde",
    )
    args = parser.parse_args()

    if args.global_:
        ziel = GLOBALER_ORDNER
    elif args.dir:
        ziel = Path(args.dir).expanduser().resolve() / ".agents"
    else:
        ok, toplevel = run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
        if not ok or not toplevel:
            print(
                "Das hier ist kein Git-Repository.\n"
                "Bitte im Projekt ausführen, oder --dir bzw. --global angeben.",
                file=sys.stderr,
            )
            return 1
        ziel = Path(toplevel).resolve() / ".agents"

    print(f"team-sync:  {WURZEL}")
    print(f"Ziel:       {ziel}")
    if args.probelauf:
        print("Probelauf, es wird nichts geschrieben.")
    print()

    erfolg = True
    print("Hooks:")
    erfolg &= hooks_schreiben(
        ziel / "hooks.json", args.python, args.entfernen, args.probelauf
    )

    print("Regeln:")
    erfolg &= texte_schreiben(
        WURZEL / "antigravity" / "rules", ziel / "rules", args.entfernen, args.probelauf
    )

    print("Workflows:")
    erfolg &= texte_schreiben(
        WURZEL / "antigravity" / "workflows",
        ziel / "workflows",
        args.entfernen,
        args.probelauf,
    )

    print()
    if not erfolg:
        print("Mit Fehlern beendet, siehe oben.", file=sys.stderr)
        return 1

    if args.entfernen:
        print("Entfernt. Antigravity einmal neu starten.")
        return 0

    print("Fertig. Antigravity einmal neu starten, damit die Hooks greifen.")

    _gitignore_hinweis(ziel)

    print()
    print("Noch nötig, falls nicht schon geschehen:")
    print("  python3 " + str(WURZEL / "scripts" / "setup_channel.py"))
    print("Prüfen:")
    print("  python3 " + str(WURZEL / "scripts" / "team_sync.py") + " doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
