"""CLI fallback / debug tool — manual pipeline triggering.

The primary path is discovery → triage → run_investigation; this CLI exists
for one-off debugging and CI-style invocation.

Examples:
    python -m alfred.cli investigate ./sample-repo 2.3.0
    python -m alfred.cli investigate https://github.com/user/repo 1.2.3 --dep openai \
        --github-owner user --github-repo repo --github-token ghp_xxx
    python -m alfred.cli poll
    python -m alfred.cli serve

GitHub credentials are PER-REQUEST: pass your own token/owner/repo to post the
verdict issue. They are used in-memory for that one run only — never stored or
logged. Without a token, the ACTION step skips cleanly.
"""

from __future__ import annotations

import argparse
import sys

from .db import Database
from .discovery import poll_once
from .events import log_event


def cmd_investigate(args: argparse.Namespace) -> int:
    from .orchestrator import DockerUnavailableError, run_investigation

    db = Database()
    try:
        inv_id = run_investigation(
            db,
            repo_source=args.repo,
            target_version=args.version,
            dependency_name=args.dep,
            github_token=args.github_token,
            github_owner=args.github_owner,
            github_repo=args.github_repo,
            trigger="manual",
        )
        inv = db.get_investigation(inv_id)
        decision = db.get_decision(inv_id)
        action = db.get_action(inv_id)
        print(f"\ninvestigation {inv_id}")
        print(f"  verdict:   {decision['verdict'] if decision else inv['verdict']}")
        print(f"  score:     {inv['compatibility_score']}")
        if action and action.get("issue_url"):
            print(f"  issue:     {action['issue_url']}")
        return 0
    except DockerUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        log_event(db, "cli", "CLI", f"investigation failed: {exc}", level="error")
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_poll(args: argparse.Namespace) -> int:
    db = Database()
    new = poll_once(db)
    print(f"discovery poll complete: {new} new change(s)")
    for change in db.list_detected_changes(limit=10):
        print(f"  [{change['triage_status']}] {change['dependency_name']} {change['latest_version']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    uvicorn.run(
        "alfred.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", args.port)),
        reload=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alfred", description="Alfred release-impact agent")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("investigate", help="manually run the pipeline (fallback/debug path)")
    inv.add_argument("repo", help="local path or git URL of a contract-compliant repo")
    inv.add_argument("version", help="target dependency version for the candidate environment")
    inv.add_argument("--dep", help="dependency name override (defaults to alfred.yaml)")
    inv.add_argument("--github-owner", help="owner of the repo the verdict issue is posted to")
    inv.add_argument("--github-repo", help="repo the verdict issue is posted to")
    inv.add_argument(
        "--github-token",
        help="your own GitHub PAT — used in-memory for this run only, never stored or logged",
    )
    inv.set_defaults(func=cmd_investigate)

    poll = sub.add_parser("poll", help="run one discovery poll now")
    poll.set_defaults(func=cmd_poll)

    serve = sub.add_parser("serve", help="start the API + dashboard")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
