"""Agent-to-agent message bus on GitHub Issues. Both assistants use this; humans read it on GitHub.

  uv run python scripts/comms.py send --to GLASS --kind question --task 1.6 --subject "..." --body "..."
        [--blocking] [--needs-human]
  uv run python scripts/comms.py inbox --me GLASS            # open issues addressed to me (compact)
  uv run python scripts/comms.py show 12                      # one issue with its comments
  uv run python scripts/comms.py reply 12 --body "..." [--close] [--kind answer]
  uv run python scripts/comms.py escalate 12 --body "..."     # mark needs-human, assign the humans
  uv run python scripts/comms.py watch --me GLASS [--interval 60] [--auto]

Protocol (docs/COMMS.md): a message is an issue; labels route it
(to:CORE / to:GLASS, kind:*, priority:*, needs-human).
A reply flips the to: label to the other side so their poll picks it up. Closing = resolved.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

CODENAMES = ("CORE", "GLASS")
HUMANS = {"CORE": "hasanza", "GLASS": "ibrahimeDEV"}
KINDS = ("question", "request", "answer", "info", "decision")
STATE_DIR = Path.home() / ".control-tower-comms"


def gh(*args: str, input_text: str | None = None) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_text)
    if res.returncode != 0:
        sys.exit(f"gh {' '.join(args[:2])} failed: {res.stderr.strip()}")
    return res.stdout


def other(me: str) -> str:
    return "GLASS" if me == "CORE" else "CORE"


def me_from_local() -> str | None:
    """Read the code name from CLAUDE.local.md if present (so skills need no argument)."""
    p = Path.cwd() / "CLAUDE.local.md"
    if p.exists():
        text = p.read_text()
        for name in CODENAMES:
            if f"assisting **{name}**" in text or f"assisting {name}" in text:
                return name
    return None


def cmd_send(a: argparse.Namespace) -> None:
    sender = a.me or me_from_local() or sys.exit("--me required (or set CLAUDE.local.md)")
    task = f"[task {a.task}]" if a.task else ""
    title = f"[{sender}→{a.to}]{task} {a.subject}"
    labels = [f"to:{a.to}", f"kind:{a.kind}", f"priority:{'blocking' if a.blocking else 'normal'}"]
    if a.needs_human:
        labels.append("needs-human")
    body = (
        f"**From:** {sender} · **To:** {a.to} · **Kind:** {a.kind} · **Task:** {a.task or '-'}\n\n"
        f'{a.body}\n\n---\n_Reply with_ `uv run python scripts/comms.py reply <n> --body "..."`'
    )
    args = ["issue", "create", "--title", title, "--body", body]
    for lab in labels:
        args += ["--label", lab]
    if a.needs_human:
        args += ["--assignee", HUMANS[a.to]]
    print(gh(*args).strip())


def _list(me: str) -> list[dict]:
    out = gh(
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        f"to:{me}",
        "--limit",
        "50",
        "--json",
        "number,title,labels,updatedAt,author,url",
    )
    return json.loads(out)


def cmd_inbox(a: argparse.Namespace) -> None:
    me = a.me or me_from_local() or sys.exit("--me required")
    items = _list(me)
    if a.json:
        print(json.dumps(items, indent=2))
        return
    if not items:
        print(f"inbox for {me}: empty")
        return
    for it in items:
        labs = ",".join(label["name"] for label in it["labels"] if not label["name"].startswith("to:"))
        print(f"#{it['number']:<4} {it['title']}  [{labs}]  {it['updatedAt'][:16]}")


def cmd_show(a: argparse.Namespace) -> None:
    # --json avoids a GraphQL field (projectCards) that older gh versions still request with --comments
    data = json.loads(
        gh("issue", "view", str(a.number), "--json", "number,title,state,labels,body,comments,url")
    )
    labels = ",".join(label["name"] for label in data["labels"])
    print(f"#{data['number']} [{data['state']}] {data['title']}")
    print(f"labels: {labels}\n{data['url']}\n\n{data['body']}")
    for c in data.get("comments", []):
        print(f"\n--- {c['author']['login']} @ {c['createdAt'][:16]} ---\n{c['body']}")


def _labels(number: int) -> set[str]:
    data = json.loads(gh("issue", "view", str(number), "--json", "labels"))
    return {label["name"] for label in data["labels"]}


def cmd_reply(a: argparse.Namespace) -> None:
    me = a.me or me_from_local() or sys.exit("--me required")
    body = f"**{me}** ({a.kind}):\n\n{a.body}"
    gh("issue", "comment", str(a.number), "--body", body)
    labs = _labels(a.number)
    edit = ["issue", "edit", str(a.number)]
    for lab in labs:
        if lab.startswith("to:") or lab.startswith("kind:"):
            edit += ["--remove-label", lab]
    edit += ["--add-label", f"to:{other(me)}", "--add-label", f"kind:{a.kind}"]
    if a.auto:
        edit += ["--add-label", "auto-handled"]
    gh(*edit)
    if a.close:
        gh("issue", "close", str(a.number), "--comment", f"Resolved by {me}.")
    print(f"replied on #{a.number} → to:{other(me)}" + (" (closed)" if a.close else ""))


def cmd_escalate(a: argparse.Namespace) -> None:
    me = a.me or me_from_local() or sys.exit("--me required")
    gh("issue", "comment", str(a.number), "--body", f"**{me}**: needs a human decision.\n\n{a.body}")
    gh(
        "issue",
        "edit",
        str(a.number),
        "--add-label",
        "needs-human",
        "--add-assignee",
        f"{HUMANS['CORE']},{HUMANS['GLASS']}",
    )
    print(f"#{a.number} escalated to humans")


def _notify(title: str, text: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", f'display notification "{text}" with title "{title}" sound name "Glass"'],
            check=False,
        )
    print(f"\a[{datetime.now().strftime('%H:%M')}] {title}: {text}", flush=True)


def _auto_handle(me: str, item: dict, repo_root: Path, model: str) -> None:
    """Headless Claude answers one kind:question. Read-only tools plus the comms script; nothing else."""
    if not shutil.which("claude"):
        print("claude CLI not found; cannot auto-handle", flush=True)
        return
    n = item["number"]
    prompt = (
        f"You are assisting {me} on the Hack the Highway project "
        "(read CLAUDE.md, .claude/rules/ownership.md, docs/COMMS.md). "
        f"GitHub issue #{n} is a question addressed to {me}. "
        f"Run `uv run python scripts/comms.py show {n}` to read it. "
        "Research the answer in this repository only (read files, run read-only commands). Then reply with "
        f'`uv run python scripts/comms.py reply {n} --kind answer --auto --body "<answer>"`. '
        "Rules: never edit files; never commit; if the question needs a code change, a decision about "
        "contracts, the planner, or anything a human should decide, instead run "
        f'`uv run python scripts/comms.py escalate {n} --body "<why>"`. '
        "Keep the answer under 200 words, cite file paths."
    )
    allowed = ",".join(
        [
            "Read",
            "Grep",
            "Glob",
            "Bash(uv run python scripts/comms.py:*)",
            "Bash(gh issue view:*)",
            "Bash(git log:*)",
            "Bash(git diff:*)",
            "Bash(ls:*)",
            "Bash(cat:*)",
        ]
    )
    print(f"auto-handling #{n} with claude ({model})...", flush=True)
    subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--allowedTools", allowed, "--max-turns", "25"],
        cwd=repo_root,
        check=False,
        timeout=900,
    )


def cmd_watch(a: argparse.Namespace) -> None:
    me = a.me or me_from_local() or sys.exit("--me required")
    STATE_DIR.mkdir(exist_ok=True)
    state_path = STATE_DIR / f"seen-{me}.json"
    seen: dict[str, str] = json.loads(state_path.read_text()) if state_path.exists() else {}
    repo_root = Path.cwd()
    print(
        f"watching inbox for {me} every {a.interval}s (auto={'on' if a.auto else 'off'}); ctrl-c to stop",
        flush=True,
    )
    while True:
        try:
            for it in _list(me):
                key = str(it["number"])
                if seen.get(key) == it["updatedAt"]:
                    continue
                seen[key] = it["updatedAt"]
                state_path.write_text(json.dumps(seen))
                labs = {label["name"] for label in it["labels"]}
                _notify(f"{me} inbox: #{it['number']}", it["title"][:80])
                if a.auto and "kind:question" in labs and "needs-human" not in labs:
                    _auto_handle(me, it, repo_root, a.model)
        except SystemExit as e:
            print(f"poll failed: {e}", flush=True)
        time.sleep(a.interval)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--me", choices=CODENAMES, help="your code name (default: from CLAUDE.local.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send")
    s.add_argument("--to", required=True, choices=CODENAMES)
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--task", default="")
    s.add_argument("--subject", required=True)
    s.add_argument("--body", required=True)
    s.add_argument("--blocking", action="store_true")
    s.add_argument("--needs-human", action="store_true")
    s.set_defaults(fn=cmd_send)

    i = sub.add_parser("inbox")
    i.add_argument("--json", action="store_true")
    i.set_defaults(fn=cmd_inbox)

    sh = sub.add_parser("show")
    sh.add_argument("number", type=int)
    sh.set_defaults(fn=cmd_show)

    r = sub.add_parser("reply")
    r.add_argument("number", type=int)
    r.add_argument("--body", required=True)
    r.add_argument("--kind", default="answer", choices=KINDS)
    r.add_argument("--close", action="store_true")
    r.add_argument("--auto", action="store_true", help="mark as answered by a headless agent")
    r.set_defaults(fn=cmd_reply)

    e = sub.add_parser("escalate")
    e.add_argument("number", type=int)
    e.add_argument("--body", required=True)
    e.set_defaults(fn=cmd_escalate)

    w = sub.add_parser("watch")
    w.add_argument("--interval", type=int, default=60)
    w.add_argument("--auto", action="store_true", help="answer kind:question issues with headless claude")
    w.add_argument("--model", default="sonnet")
    w.set_defaults(fn=cmd_watch)

    a = ap.parse_args()
    os.chdir(Path(__file__).resolve().parents[1])
    a.fn(a)


if __name__ == "__main__":
    main()
