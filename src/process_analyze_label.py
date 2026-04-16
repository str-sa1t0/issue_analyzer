#!/usr/bin/env python3
"""Process GitLab issues/work items that have a trigger label."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from .analyze_issue import generate_analysis, is_analysis_comment
    from .env_config import get_env, get_gitlab_project_ref, load_project_env
    from .fetch_issue import fetch_issue_data, write_issue_json
    from .post_comment import post_markdown_comment
except ImportError:
    from analyze_issue import generate_analysis, is_analysis_comment  # type: ignore
    from env_config import get_env, get_gitlab_project_ref, load_project_env  # type: ignore
    from fetch_issue import fetch_issue_data, write_issue_json  # type: ignore
    from post_comment import post_markdown_comment  # type: ignore


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="analyze", help="trigger label name")
    ap.add_argument("--processed-label", default="analyzed", help="label to add after success")
    ap.add_argument("--state", default="opened", help="GitLab issue state filter")
    ap.add_argument("--limit", type=int, default=20, help="max issues to process per pass")
    ap.add_argument(
        "--artifacts-dir",
        help="optional directory for fetched issue JSON and generated Markdown",
    )
    ap.add_argument(
        "--interval",
        type=int,
        default=0,
        help="polling interval in seconds; 0 runs once and exits",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and analyze without posting comments or mutating labels",
    )
    return ap.parse_args()


def api_get(base_url: str, token: str, path: str, **params) -> dict | list:
    response = requests.get(
        f"{base_url}/api/v4{path}",
        headers={"PRIVATE-TOKEN": token},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def api_put(base_url: str, token: str, path: str, **data) -> dict:
    response = requests.put(
        f"{base_url}/api/v4{path}",
        headers={"PRIVATE-TOKEN": token},
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def list_labeled_issues(
    base_url: str,
    token: str,
    project_ref: str,
    label: str,
    state: str,
    limit: int,
) -> list[dict]:
    issues: list[dict] = []
    page = 1
    encoded_project_ref = quote(str(project_ref), safe="")
    while len(issues) < limit:
        batch = api_get(
            base_url,
            token,
            f"/projects/{encoded_project_ref}/issues",
            labels=label,
            state=state,
            order_by="updated_at",
            sort="asc",
            per_page=min(100, limit),
            page=page,
        )
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                issues.append(item)
                if len(issues) >= limit:
                    break
        if len(batch) < min(100, limit):
            break
        page += 1
    return issues


def merge_labels(current: list[str], add: list[str], remove: list[str]) -> list[str]:
    merged = [label for label in current if label not in remove]
    for label in add:
        if label and label not in merged:
            merged.append(label)
    return merged


def update_issue_labels(
    base_url: str,
    token: str,
    project_ref: str,
    issue_iid: int,
    labels: list[str],
) -> dict:
    encoded_project_ref = quote(str(project_ref), safe="")
    return api_put(
        base_url,
        token,
        f"/projects/{encoded_project_ref}/issues/{issue_iid}",
        labels=",".join(labels),
    )


def issue_has_analysis_comment(issue: dict) -> bool:
    notes = issue.get("notes") or []
    if not isinstance(notes, list):
        return False
    for note in notes:
        if not isinstance(note, dict):
            continue
        if is_analysis_comment(str(note.get("body") or "")):
            return True
    return False


def artifact_paths(root: Path, issue_iid: int) -> tuple[Path, Path]:
    issue_dir = root / f"issue-{issue_iid}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    return issue_dir / "issue.json", issue_dir / "analysis.md"


def process_issue(
    base_url: str,
    token: str,
    project_ref: str,
    issue_stub: dict,
    trigger_label: str,
    processed_label: str,
    artifacts_dir: Path | None,
    dry_run: bool,
) -> str:
    issue_iid = int(issue_stub["iid"])
    issue_data = fetch_issue_data(
        base_url=base_url,
        token=token,
        project_ref=project_ref,
        iid=issue_iid,
        project_path=None,
    )
    analysis_path: Path | None = None
    if artifacts_dir is not None:
        issue_json_path, analysis_path = artifact_paths(artifacts_dir, issue_iid)
        write_issue_json(issue_data, str(issue_json_path))

    if issue_has_analysis_comment(issue_data):
        if not dry_run:
            current_labels = [str(label) for label in (issue_data.get("labels") or [])]
            merged = merge_labels(current_labels, [processed_label], [trigger_label])
            update_issue_labels(base_url, token, project_ref, issue_iid, merged)
        return "skipped_existing_analysis"

    analysis = generate_analysis(
        issue=issue_data,
        model=get_env("LLM_MODEL", "gemma4:26b") or "gemma4:26b",
        host=get_env("LLM_BASE_URL", "http://127.0.0.1:11434") or "http://127.0.0.1:11434",
        timeout=600,
        api_style=get_env("LLM_API_STYLE", "ollama") or "ollama",
        api_key=get_env("LLM_API_KEY"),
    )
    if analysis_path is not None:
        analysis_path.write_text(analysis + "\n", encoding="utf-8")

    if dry_run:
        return "analyzed_dry_run"

    post_markdown_comment(
        base_url=base_url,
        token=token,
        project_ref=project_ref,
        issue_iid=issue_iid,
        body=analysis,
    )
    current_labels = [str(label) for label in (issue_data.get("labels") or [])]
    merged = merge_labels(current_labels, [processed_label], [trigger_label])
    update_issue_labels(base_url, token, project_ref, issue_iid, merged)
    return "processed"


def process_pass(args: argparse.Namespace) -> int:
    load_project_env()
    token = get_env("GITLAB_TOKEN")
    base_url = get_env("GITLAB_URL")
    project_ref = get_gitlab_project_ref()
    if not token:
        print("GITLAB_TOKEN is not set", file=sys.stderr)
        return 2
    if not base_url:
        print("GITLAB_URL is not set", file=sys.stderr)
        return 2
    if not project_ref:
        print("GITLAB_PROJECT_ID or GITLAB_PROJECT is not set", file=sys.stderr)
        return 2

    try:
        issues = list_labeled_issues(
            base_url=base_url,
            token=token,
            project_ref=project_ref,
            label=args.label,
            state=args.state,
            limit=args.limit,
        )
    except requests.HTTPError as e:
        body_text = e.response.text[:400] if e.response is not None else ""
        print(f"GitLab API error: {e} body={body_text}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"GitLab API request failed: {e}", file=sys.stderr)
        return 3

    if not issues:
        print("no labeled issues found")
        return 0

    artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else None
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, str | int]] = []
    for issue_stub in issues:
        iid = int(issue_stub["iid"])
        title = str(issue_stub.get("title") or "")
        try:
            status = process_issue(
                base_url=base_url,
                token=token,
                project_ref=str(project_ref),
                issue_stub=issue_stub,
                trigger_label=args.label,
                processed_label=args.processed_label,
                artifacts_dir=artifacts_dir,
                dry_run=args.dry_run,
            )
            results.append({"iid": iid, "title": title, "status": status})
        except requests.HTTPError as e:
            body_text = e.response.text[:400] if e.response is not None else ""
            print(f"issue {iid}: GitLab API error: {e} body={body_text}", file=sys.stderr)
            results.append({"iid": iid, "title": title, "status": "error"})
        except requests.RequestException as e:
            print(f"issue {iid}: GitLab API request failed: {e}", file=sys.stderr)
            results.append({"iid": iid, "title": title, "status": "error"})
        except ValueError as e:
            print(f"issue {iid}: processing error: {e}", file=sys.stderr)
            results.append({"iid": iid, "title": title, "status": "error"})

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] != "error" for result in results) else 4


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        return process_pass(args)

    while True:
        exit_code = process_pass(args)
        if exit_code not in {0, 4}:
            return exit_code
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
