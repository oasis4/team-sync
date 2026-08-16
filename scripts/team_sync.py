#!/usr/bin/env python3
"""
team-sync Kommandozeile.

Alles, was die Slash-Commands im Channel tun, läuft über dieses
Skript. Der erste Entwurf hat stattdessen in jedem Command in acht
Prosaschritten beschrieben, welche git-Befehle Claude ausführen soll.
Das kostet bei jedem Aufruf Tokens für Anweisungen, die sich nie
ändern, und das Ergebnis hängt davon ab, ob die Schritte diesmal genau
befolgt wurden. Dateiname, Kopffelder, Commit und Push sind aber immer
gleich, also gehören sie in Code.

Was bleibt für Claude: den Inhalt formulieren. Das ist der Teil, den
ein Skript nicht kann.

Aufruf:

    python3 team_sync.py ask --to max --titel "..." --text "..."
    python3 team_sync.py fragen --offen
    python3 team_sync.py answer --id 2026-08-16-1830-lars-an-max --text "..."
    python3 team_sync.py decide --titel "..." --entscheidung "..." --begruendung "..."
    python3 team_sync.py sync --text "..."
    python3 team_sync.py uebersicht
    python3 team_sync.py kontext
    python3 team_sync.py doctor
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import frontmatter, render
from lib.channel import (
    CHANNEL_BRANCH,
    ChannelLock,
    channel_is_ready,
    describe_age,
    get_agent_name,
    get_channel_dir,
    get_current_branch,
    get_project_dir,
    list_worktrees,
    now_id,
    now_stamp,
    pull_channel,
    read_text,
    run_git,
    setup_hint,
    setup_stdio,
    slugify,
    touch_throttle,
    write_and_push,
)
from lib.transcript import summarize

EXIT_OK = 0
EXIT_FEHLER = 1
EXIT_KEIN_SETUP = 2


# ---------------------------------------------------------------------------
# Gemeinsames
# ---------------------------------------------------------------------------


class Kontext:
    """Bündelt, was praktisch jedes Kommando braucht."""

    def __init__(self):
        self.project_dir = get_project_dir()
        self.channel_dir = get_channel_dir(self.project_dir)
        self.me = get_agent_name(self.project_dir)
        self.branch = get_current_branch(self.project_dir)

    def bereit(self) -> bool:
        return channel_is_ready(self.channel_dir)


def text_argument(args) -> str:
    """
    Holt den Text eines Kommandos.

    Drei Wege, weil mehrzeiliger Text mit Sonderzeichen je nach Shell
    unterschiedlich schwierig zu übergeben ist: direkt als Argument,
    aus einer Datei, oder über die Standardeingabe.
    """
    if getattr(args, "text_file", None):
        try:
            return Path(args.text_file).read_text(encoding="utf-8").strip()
        except Exception as exc:
            fehler(f"Textdatei nicht lesbar: {exc}")
            sys.exit(EXIT_FEHLER)

    text = getattr(args, "text", None) or ""
    if text.strip() == "-":
        return sys.stdin.read().strip()
    return text.strip()


def fehler(nachricht: str):
    print(f"Fehler: {nachricht}", file=sys.stderr)


def kein_setup(ctx: Kontext) -> int:
    print(setup_hint(ctx.channel_dir))
    return EXIT_KEIN_SETUP


def melde(erfolg: bool, pfad: str, was: str) -> int:
    """
    Meldet das Ergebnis eines Schreibvorgangs.

    Der Unterschied zwischen "geschrieben" und "gepusht" ist für das
    Team wichtig: Was nur lokal liegt, sieht sonst niemand. Der nächste
    Hook holt es nach, aber der Nutzer sollte es wissen.
    """
    if erfolg:
        print(f"{was} angelegt und gepusht: {pfad}")
        return EXIT_OK
    print(
        f"{was} lokal angelegt: {pfad}\n"
        "Der Push hat nicht geklappt (kein Netz oder kein Remote?). "
        "Der nächste Sync schiebt es nach."
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def cmd_ask(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)

    ziel = args.to.strip()
    text = text_argument(args)
    if not text:
        fehler("Die Frage ist leer.")
        return EXIT_FEHLER

    titel = (args.titel or text.splitlines()[0])[:80].strip()
    dateiname = f"{now_id()}-{ctx.me}-an-{slugify(ziel)}.md"

    inhalt = frontmatter.build(
        {
            "typ": "frage",
            "von": ctx.me,
            "an": slugify(ziel),
            "erstellt": now_stamp(),
            "branch": ctx.branch,
            "status": "offen",
            "titel": titel,
        },
        f"# {titel}\n\n{text}\n",
    )

    erfolg = write_and_push(
        ctx.channel_dir,
        f"questions/{dateiname}",
        inhalt,
        f"frage: {ctx.me} an {slugify(ziel)} - {titel[:50]}",
    )
    return melde(erfolg, f"questions/{dateiname}", "Frage")


# ---------------------------------------------------------------------------
# fragen (auflisten)
# ---------------------------------------------------------------------------


def cmd_fragen(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)

    pull_channel(ctx.channel_dir)

    person = args.person or ctx.me
    if args.gestellt:
        fragen = render.open_questions_from(ctx.channel_dir, person)
        ueberschrift = f"Offene Fragen von {person}"
    else:
        fragen = render.open_questions_for(ctx.channel_dir, person)
        ueberschrift = f"Offene Fragen an {person}"

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": frage["path"].stem,
                        "von": frage["von"],
                        "an": frage["an"],
                        "titel": frage["titel"],
                        "erstellt": frage["erstellt"],
                        "branch": frage["branch"],
                        "text": frage["body"],
                    }
                    for frage in fragen
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK

    if not fragen:
        print(f"{ueberschrift}: keine.")
        return EXIT_OK

    print(f"{ueberschrift}:\n")
    for frage in fragen:
        print(f"## {frage['titel'] or frage['path'].stem}")
        print(f"id: {frage['path'].stem}")
        print(
            f"von: {frage['von']}, {describe_age(frage['erstellt'])}, "
            f"Branch {frage['branch'] or '?'}"
        )
        print()
        print(frage["body"])
        print()
    return EXIT_OK


# ---------------------------------------------------------------------------
# answer
# ---------------------------------------------------------------------------


def cmd_answer(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)

    antwort = text_argument(args)
    if not antwort:
        fehler("Die Antwort ist leer.")
        return EXIT_FEHLER

    with ChannelLock(ctx.channel_dir):
        pull_channel(ctx.channel_dir)

        pfad = ctx.channel_dir / "questions" / f"{args.id}.md"
        if not pfad.is_file():
            fehler(f"Keine Frage mit der id {args.id} gefunden.")
            return EXIT_FEHLER

        felder, rumpf = frontmatter.parse(read_text(pfad))
        if frontmatter.get(felder, "status", "offen").lower() != "offen":
            print(f"Die Frage {args.id} ist bereits beantwortet.")
            return EXIT_OK

        felder["status"] = "beantwortet"
        felder["beantwortet_von"] = ctx.me
        felder["beantwortet_am"] = now_stamp()

        rumpf = (
            rumpf.rstrip()
            + f"\n\n## Antwort ({ctx.me}, {now_stamp()})\n\n{antwort}\n"
        )

        try:
            pfad.write_text(frontmatter.build(felder, rumpf), encoding="utf-8", newline="\n")
        except Exception as exc:
            fehler(f"Antwort konnte nicht geschrieben werden: {exc}")
            return EXIT_FEHLER

        from lib.channel import push_channel

        erfolg = push_channel(
            ctx.channel_dir, f"antwort: {ctx.me} auf {args.id}"
        )

    return melde(erfolg, f"questions/{args.id}.md", "Antwort")


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


def cmd_decide(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)

    titel = args.titel.strip()
    if not titel:
        fehler("Die Entscheidung braucht einen Titel.")
        return EXIT_FEHLER

    abschnitte = [f"# Entscheidung: {titel}", ""]

    if args.kontext:
        abschnitte += ["**Worum ging es**", "", args.kontext.strip(), ""]

    abschnitte += ["**Was wurde entschieden**", "", args.entscheidung.strip(), ""]

    if args.begruendung:
        abschnitte += ["**Warum**", "", args.begruendung.strip(), ""]

    if args.alternativen:
        abschnitte += ["**Verworfene Alternativen**", ""]
        for alternative in args.alternativen:
            abschnitte.append(f"- {alternative.strip()}")
        abschnitte.append("")

    if args.betrifft:
        abschnitte += ["**Betrifft**", ""]
        for eintrag in args.betrifft:
            abschnitte.append(f"- {eintrag.strip()}")
        abschnitte.append("")

    dateiname = f"{now_id()}-{ctx.me}-{slugify(titel)[:50]}.md"
    inhalt = frontmatter.build(
        {
            "typ": "entscheidung",
            "person": ctx.me,
            "erstellt": now_stamp(),
            "branch": ctx.branch,
            "titel": titel,
        },
        "\n".join(abschnitte),
    )

    erfolg = write_and_push(
        ctx.channel_dir,
        f"decisions/{dateiname}",
        inhalt,
        f"entscheidung: {titel[:60]}",
    )
    return melde(erfolg, f"decisions/{dateiname}", "Entscheidung")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def cmd_sync(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)

    freitext = text_argument(args)
    dateien = []
    if args.transcript:
        dateien = summarize(args.transcript, ctx.project_dir)["dateien"]
    if args.datei:
        dateien = sorted(set(dateien) | set(args.datei))

    inhalt = render.render_status(
        person=ctx.me,
        branch=ctx.branch,
        stamp=now_stamp(),
        quelle="manuell",
        dateien=dateien,
        freitext=freitext or "_ohne Beschreibung_",
    )

    erfolg = write_and_push(
        ctx.channel_dir,
        f"status/{ctx.me}.md",
        inhalt,
        f"status: {ctx.me} - {now_stamp()}",
    )

    # Verhindert, dass der automatische Zwischenstand den gerade von
    # Claude formulierten Status wenige Minuten später wieder durch
    # eine grobe Heuristik ersetzt.
    touch_throttle(ctx.project_dir)

    return melde(erfolg, f"status/{ctx.me}.md", "Status")


# ---------------------------------------------------------------------------
# uebersicht, kontext
# ---------------------------------------------------------------------------


def cmd_uebersicht(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)
    pull_channel(ctx.channel_dir)
    print(render.build_overview(ctx.channel_dir, ctx.me))
    return EXIT_OK


def cmd_kontext(args) -> int:
    ctx = Kontext()
    if not ctx.bereit():
        return kein_setup(ctx)
    if not args.kein_pull:
        pull_channel(ctx.channel_dir)
    text = render.build_context(ctx.channel_dir, ctx.me)
    print(text or "(Channel ist leer, kein Kontext)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args) -> int:
    setup_stdio()
    ctx = Kontext()
    probleme = []

    print("team-sync Diagnose\n")
    print(f"Python:            {sys.version.split()[0]} ({sys.executable})")

    ok, version = run_git(["--version"], cwd=ctx.project_dir)
    print(f"Git:               {version if ok else 'NICHT GEFUNDEN'}")
    if not ok:
        probleme.append("git ist nicht aufrufbar.")

    print(f"Projekt:           {ctx.project_dir}")
    print(f"Aktueller Branch:  {ctx.branch}")
    print(f"Eigener Name:      {ctx.me}")
    if ctx.me == "unbekannt":
        probleme.append(
            "Kein Name ermittelbar. Setze git config user.name oder "
            "die Umgebungsvariable TEAM_AGENT_NAME."
        )

    print(f"Channel-Branch:    {CHANNEL_BRANCH}")
    print(f"Channel-Ordner:    {ctx.channel_dir}")

    if not ctx.bereit():
        probleme.append(
            "Der Channel ist nicht eingerichtet. Einmalig "
            "'python3 scripts/setup_channel.py' im Projekt ausführen."
        )
    else:
        print("Channel:           vorhanden")

        ok, remote = run_git(["remote", "get-url", "origin"], cwd=ctx.channel_dir)
        print(f"Remote:            {remote if ok and remote else 'keines'}")
        if not ok or not remote:
            probleme.append(
                "Der Channel hat kein Remote. Ohne Remote bleibt alles lokal, "
                "das Team sieht nichts davon."
            )

        ok, upstream = run_git(
            ["rev-parse", "--abbrev-ref", "@{upstream}"], cwd=ctx.channel_dir
        )
        print(f"Upstream:          {upstream if ok and upstream else 'keiner'}")
        if not ok or not upstream:
            probleme.append(
                f"Der Channel-Branch verfolgt keinen Remote-Branch. "
                f"Einmalig: git -C \"{ctx.channel_dir}\" push -u origin {CHANNEL_BRANCH}"
            )

        for unterordner in ("status", "questions", "decisions"):
            pfad = ctx.channel_dir / unterordner
            anzahl = len(list(pfad.glob("*.md"))) if pfad.is_dir() else 0
            zustand = "fehlt" if not pfad.is_dir() else f"{anzahl} Einträge"
            print(f"  {unterordner:<16} {zustand}")

        eigener_status = ctx.channel_dir / "status" / f"{ctx.me}.md"
        if eigener_status.is_file():
            stand = render.read_status(eigener_status)
            print(
                f"Eigener Status:    {stand['aktualisiert']} "
                f"({describe_age(stand['aktualisiert'])}, {stand['quelle']})"
            )
        else:
            print("Eigener Status:    noch keiner geschrieben")

    worktrees = list_worktrees(ctx.project_dir)
    if worktrees:
        print("\nWorktrees:")
        for pfad, branch in worktrees:
            print(f"  {branch:<20} {pfad}")

    if probleme:
        print("\nGefundene Probleme:")
        for problem in probleme:
            print(f"  - {problem}")
        return EXIT_FEHLER

    print("\nAlles in Ordnung.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------


def _text_argumente(parser, hilfe):
    parser.add_argument("--text", help=f"{hilfe} ('-' liest von der Standardeingabe)")
    parser.add_argument("--text-file", dest="text_file", help="Datei mit dem Text")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="team_sync",
        description="Team-Channel für parallele Claude-Code-Sessions am selben Repo.",
    )
    sub = parser.add_subparsers(dest="kommando", required=True)

    p_ask = sub.add_parser("ask", help="Frage an ein Teammitglied hinterlegen")
    p_ask.add_argument("--to", required=True, help="Name der Zielperson")
    p_ask.add_argument("--titel", help="Kurztitel der Frage")
    _text_argumente(p_ask, "Die Frage")
    p_ask.set_defaults(func=cmd_ask)

    p_fragen = sub.add_parser("fragen", help="Offene Fragen auflisten")
    p_fragen.add_argument("--person", help="Für wen (Vorgabe: man selbst)")
    p_fragen.add_argument(
        "--gestellt",
        action="store_true",
        help="Statt der Fragen an einen selbst die eigenen offenen Fragen zeigen",
    )
    p_fragen.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    p_fragen.set_defaults(func=cmd_fragen)

    p_answer = sub.add_parser("answer", help="Eine offene Frage beantworten")
    p_answer.add_argument("--id", required=True, help="Dateiname der Frage ohne .md")
    _text_argumente(p_answer, "Die Antwort")
    p_answer.set_defaults(func=cmd_answer)

    p_decide = sub.add_parser("decide", help="Entscheidung protokollieren")
    p_decide.add_argument("--titel", required=True)
    p_decide.add_argument("--entscheidung", required=True, help="Was wurde entschieden")
    p_decide.add_argument("--kontext", help="Worum ging es")
    p_decide.add_argument("--begruendung", help="Warum so entschieden")
    p_decide.add_argument(
        "--alternative",
        dest="alternativen",
        action="append",
        help="Verworfene Alternative samt Grund, mehrfach angebbar",
    )
    p_decide.add_argument(
        "--betrifft",
        action="append",
        help="Betroffene Komponente oder Datei, mehrfach angebbar",
    )
    p_decide.set_defaults(func=cmd_decide)

    p_sync = sub.add_parser("sync", help="Eigenen Status sofort aktualisieren")
    _text_argumente(p_sync, "Die Zusammenfassung")
    p_sync.add_argument("--transcript", help="Pfad zum Transkript für die Dateiliste")
    p_sync.add_argument(
        "--datei", action="append", help="Angefasste Datei, mehrfach angebbar"
    )
    p_sync.set_defaults(func=cmd_sync)

    p_ueber = sub.add_parser("uebersicht", help="Wer arbeitet woran, was ist offen")
    p_ueber.set_defaults(func=cmd_uebersicht)

    p_kontext = sub.add_parser(
        "kontext", help="Den Sessionstart-Kontext ausgeben (zum Prüfen)"
    )
    p_kontext.add_argument("--kein-pull", dest="kein_pull", action="store_true")
    p_kontext.set_defaults(func=cmd_kontext)

    p_doctor = sub.add_parser("doctor", help="Einrichtung prüfen")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv=None) -> int:
    setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return EXIT_FEHLER
    except Exception as exc:
        fehler(str(exc))
        return EXIT_FEHLER


if __name__ == "__main__":
    sys.exit(main())
