#!/usr/bin/env python3
"""Parse a GitLab issue reference into GitLab API coordinates.

Accepts:
  - Full URL: https://gitlab.example.com/group/sub/proj/-/issues/42
  - Full URL: https://gitlab.example.com/group/sub/proj/-/work_items/42
  - Shorthand: group/sub/proj#42    (requires GITLAB_URL in env)
  - Bare iid:  42                   (requires GITLAB_URL and GITLAB_PROJECT_ID or GITLAB_PROJECT in env)

Prints JSON to stdout. Exits non-zero on parse errors with a message on stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

try:
    from .env_config import get_env, get_gitlab_project_ref, load_project_env
except ImportError:
    from env_config import get_env, get_gitlab_project_ref, load_project_env  # type: ignore


def parse(ref: str) -> dict:
    load_project_env()
    ref = ref.strip()

    # Full URL form
    if ref.startswith("http://") or ref.startswith("https://"):
        u = urlparse(ref)
        base = f"{u.scheme}://{u.netloc}"
        # Path looks like: /group/sub/project/-/issues/42[/...]
        # or:             /group/sub/project/-/work_items/42[/...]
        m = re.match(r"^/(.+?)/-/(?:issues|work_items)/(\d+)", u.path)
        if not m:
            raise ValueError(f"URL does not look like a GitLab issue: {ref}")
        return {
            "base_url": base,
            "project_path": m.group(1),
            "project_ref": m.group(1),
            "issue_iid": int(m.group(2)),
        }

    # Shorthand: group/project#42
    m = re.match(r"^(.+)#(\d+)$", ref)
    if m:
        base = get_env("GITLAB_URL")
        if not base:
            raise ValueError(
                "Shorthand form 'group/project#NN' requires GITLAB_URL env var"
            )
        return {
            "base_url": base.rstrip("/"),
            "project_path": m.group(1),
            "project_ref": m.group(1),
            "issue_iid": int(m.group(2)),
        }

    # Bare iid
    if ref.isdigit():
        base = get_env("GITLAB_URL")
        project_path = get_env("GITLAB_PROJECT")
        project_ref = get_gitlab_project_ref()
        if not base or not project_ref:
            raise ValueError(
                "Bare issue id requires GITLAB_URL and either GITLAB_PROJECT_ID or GITLAB_PROJECT env vars"
            )
        return {
            "base_url": base.rstrip("/"),
            "project_path": project_path,
            "project_ref": project_ref,
            "issue_iid": int(ref),
        }

    raise ValueError(f"Could not parse issue reference: {ref!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", help="issue URL, shorthand (group/proj#42), or bare iid")
    args = ap.parse_args()
    try:
        print(json.dumps(parse(args.ref), ensure_ascii=False))
    except ValueError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
