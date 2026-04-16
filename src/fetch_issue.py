#!/usr/bin/env python3
"""Fetch a GitLab issue and its discussion, saving a trimmed JSON to ./issue.json.

Requires GITLAB_TOKEN in the environment. GITLAB_URL is inferred from the URL
when the full URL form is used, but can be overridden via env.

System notes (auto-generated labels/state changes) are filtered out — they add
noise without signal for a requirement analysis.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import quote

import requests

try:
    from .env_config import get_env, load_project_env
    from .parse_url import parse
except ImportError:
    from env_config import get_env, load_project_env  # type: ignore
    from parse_url import parse  # type: ignore  # local import when run as a script


def api_get(base_url: str, token: str, path: str, **params) -> dict | list:
    r = requests.get(
        f"{base_url}/api/v4{path}",
        headers={"PRIVATE-TOKEN": token},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def collect_notes(base_url: str, token: str, project_id: str, iid: int) -> list[dict]:
    notes: list[dict] = []
    page = 1
    while True:
        batch = api_get(
            base_url,
            token,
            f"/projects/{project_id}/issues/{iid}/notes",
            per_page=100,
            page=page,
            sort="asc",
            order_by="created_at",
        )
        if not isinstance(batch, list) or not batch:
            break
        notes.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # Filter out system notes (label changes, assignment events, etc.)
    return [
        {
            "id": n["id"],
            "author": (n.get("author") or {}).get("username"),
            "created_at": n.get("created_at"),
            "body": n.get("body"),
        }
        for n in notes
        if not n.get("system")
    ]


def infer_project_path(issue: dict, fallback: str | None) -> str | None:
    if fallback:
        return fallback
    references = issue.get("references") or {}
    full_ref = references.get("full")
    if isinstance(full_ref, str) and "#" in full_ref:
        return full_ref.rsplit("#", 1)[0]
    return None


def fetch_issue_data(
    base_url: str,
    token: str,
    project_ref: str,
    iid: int,
    project_path: str | None = None,
) -> dict:
    issue = api_get(base_url, token, f"/projects/{quote(str(project_ref), safe='')}/issues/{iid}")
    notes = collect_notes(base_url, token, quote(str(project_ref), safe=""), iid)
    assert isinstance(issue, dict)
    inferred_project_path = infer_project_path(issue, project_path)
    return {
        "base_url": base_url,
        "project_path": inferred_project_path,
        "project_ref": project_ref,
        "issue_iid": iid,
        "web_url": issue.get("web_url"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "labels": issue.get("labels", []),
        "assignees": [a.get("username") for a in (issue.get("assignees") or [])],
        "author": (issue.get("author") or {}).get("username"),
        "milestone": (issue.get("milestone") or {}).get("title"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "due_date": issue.get("due_date"),
        "description": issue.get("description") or "",
        "notes": notes,
    }


def write_issue_json(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    load_project_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="issue URL or shorthand")
    ap.add_argument("--out", default="issue.json", help="output path (default: ./issue.json)")
    args = ap.parse_args()

    token = get_env("GITLAB_TOKEN")
    if not token:
        print("GITLAB_TOKEN is not set (.env aliases GitLabToken / GLToken are also supported)", file=sys.stderr)
        return 2

    try:
        ref = parse(args.url)
    except ValueError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 2

    base = ref["base_url"]
    iid = ref["issue_iid"]

    try:
        out = fetch_issue_data(
            base_url=base,
            token=token,
            project_ref=str(ref["project_ref"]),
            iid=iid,
            project_path=ref.get("project_path"),
        )
    except requests.HTTPError as e:
        print(f"GitLab API error: {e} body={e.response.text[:400]}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"GitLab API request failed: {e}", file=sys.stderr)
        return 3

    write_issue_json(out, args.out)
    print(f"wrote {args.out}: title={out['title']!r}, notes={len(out['notes'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
