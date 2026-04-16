#!/usr/bin/env python3
"""Post a Markdown comment to a GitLab issue.

Requires GITLAB_TOKEN in the environment and explicit user confirmation upstream —
this script is the execution step only; the decision to post must already be made.
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import quote

import requests

try:
    from .env_config import get_env, load_project_env
    from .parse_url import parse
except ImportError:
    from env_config import get_env, load_project_env  # type: ignore  # local import when run as a script
    from parse_url import parse  # type: ignore  # local import when run as a script


def fetch_issue_web_url(base_url: str, token: str, project_ref: str, iid: int) -> str | None:
    response = requests.get(
        f"{base_url}/api/v4/projects/{project_ref}/issues/{iid}",
        headers={"PRIVATE-TOKEN": token},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    web_url = payload.get("web_url")
    return web_url if isinstance(web_url, str) else None


def post_markdown_comment(
    base_url: str,
    token: str,
    project_ref: str,
    issue_iid: int,
    body: str,
) -> tuple[dict, str | None]:
    response = requests.post(
        f"{base_url}/api/v4/projects/{quote(str(project_ref), safe='')}/issues/{issue_iid}/notes",
        headers={"PRIVATE-TOKEN": token},
        data={"body": body},
        timeout=30,
    )
    response.raise_for_status()
    note = response.json()
    issue_web_url = fetch_issue_web_url(
        base_url,
        token,
        quote(str(project_ref), safe=""),
        issue_iid,
    )
    assert isinstance(note, dict)
    return note, issue_web_url


def load_body(body: str | None, body_file: str | None) -> str:
    if body_file:
        with open(body_file, "r", encoding="utf-8") as f:
            loaded_body = f.read()
    else:
        loaded_body = body or ""
    return loaded_body.strip()


def main() -> int:
    load_project_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="issue URL or shorthand")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--body", help="Markdown body (inline)")
    g.add_argument("--body-file", help="path to a file containing the Markdown body")
    args = ap.parse_args()

    token = get_env("GITLAB_TOKEN")
    if not token:
        print("GITLAB_TOKEN is not set (.env aliases GitLabToken / GLToken are also supported)", file=sys.stderr)
        return 2

    body = load_body(args.body, args.body_file)
    if not body:
        print("refusing to post an empty comment", file=sys.stderr)
        return 2

    try:
        ref = parse(args.url)
    except ValueError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 2

    try:
        note, issue_web_url = post_markdown_comment(
            base_url=ref["base_url"],
            token=token,
            project_ref=str(ref["project_ref"]),
            issue_iid=ref["issue_iid"],
            body=body,
        )
    except requests.HTTPError as e:
        body_text = e.response.text[:400] if e.response is not None else ""
        print(f"GitLab API error: {e} body={body_text}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"GitLab API request failed: {e}", file=sys.stderr)
        return 3

    # Derive a friendly URL to the specific comment
    issue_url = f"{issue_web_url or 'unknown'}#note_{note.get('id')}"
    print(f"posted: note_id={note.get('id')} url={issue_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
