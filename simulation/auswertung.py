"""
Zeitleiste einer Simulation: Channel, Code und was in beiden Sitzungen geschah.

Aufruf: python3 auswertung.py <sim-ordner> [--voll]
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SIM = Path(sys.argv[1]).resolve()
VOLL = "--voll" in sys.argv
TEAM = SIM / "team"


def kurz(text, laenge=220):
    text = " ".join(str(text).split())
    return text if VOLL or len(text) <= laenge else text[:laenge] + " …"


def zeit(stempel):
    try:
        t = datetime.fromisoformat(stempel.replace("Z", "+00:00"))
        return t.astimezone().strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


def ereignisse(person):
    dateien = sorted((SIM / f"conf-{person}" / "projects").glob("*/*.jsonl"))
    for datei in dateien:
        for zeile in datei.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(zeile)
            except Exception:
                continue
            t = zeit(e.get("timestamp", ""))
            typ = e.get("type")
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            inhalt = msg.get("content")
            if typ == "attachment":
                anhang = e.get("attachment") or {}
                art = anhang.get("type", "")
                if "hook" in art:
                    text = anhang.get("content") or anhang.get("stdout") or anhang.get("additionalContext") or ""
                    if isinstance(text, list):
                        text = " ".join(map(str, text))
                    name = anhang.get("hookName") or anhang.get("hookEvent") or ""
                    if text:
                        yield t, "HOOK", f"[{art} {name}] {kurz(text, 300)}"
                continue
            if typ == "user":
                if isinstance(inhalt, str):
                    if "task-notification" in inhalt:
                        yield t, "WECKRUF", kurz(inhalt, 400)
                    else:
                        yield t, "NUTZER", kurz(inhalt)
                elif isinstance(inhalt, list):
                    for teil in inhalt:
                        if not isinstance(teil, dict):
                            continue
                        if teil.get("type") == "tool_result":
                            ergebnis = teil.get("content")
                            if isinstance(ergebnis, list):
                                ergebnis = " ".join(
                                    x.get("text", "") for x in ergebnis if isinstance(x, dict)
                                )
                            fehler = " FEHLER" if teil.get("is_error") else ""
                            yield t, "ERGEBNIS" + fehler, kurz(ergebnis, 260)
                        elif teil.get("type") == "text":
                            text = teil.get("text", "")
                            art = "WECKRUF" if "task-notification" in text else "NUTZER"
                            yield t, art, kurz(text, 400)
            elif typ == "assistant" and isinstance(inhalt, list):
                for teil in inhalt:
                    if not isinstance(teil, dict):
                        continue
                    if teil.get("type") == "text" and teil.get("text", "").strip():
                        yield t, "CLAUDE", kurz(teil["text"], 400)
                    elif teil.get("type") == "tool_use":
                        eingabe = teil.get("input", {})
                        beschreibung = eingabe.get("command") or eingabe.get("file_path") or json.dumps(eingabe)[:150]
                        yield t, f"WERKZEUG {teil.get('name')}", kurz(beschreibung, 300)
            elif typ == "system":
                untertyp = e.get("subtype", "")
                if untertyp not in ("turn_duration", "stop_hook_summary"):
                    yield t, "SYSTEM", kurz(e.get("content") or untertyp)


def git_log(branch, format_="%ad %s"):
    return subprocess.run(
        ["git", "log", "--reverse", f"--format={format_}", "--date=format:%H:%M:%S", branch],
        cwd=TEAM / "remote.git", capture_output=True, text=True,
    ).stdout.strip()


print("=" * 100)
print("CHANNEL (team-channel auf dem Remote)")
print("=" * 100)
print(git_log("team-channel"))
print()
print("=" * 100)
print("CODE (main auf dem Remote)")
print("=" * 100)
print(git_log("main", "%ad %an: %s"))
for person in ("lars", "max"):
    print()
    print("=" * 100)
    print(f"SITZUNG {person.upper()}")
    print("=" * 100)
    for t, art, text in ereignisse(person):
        print(f"{t} {art:<18} {text}")
