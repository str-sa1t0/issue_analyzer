#!/usr/bin/env python3
"""Analyze a fetched GitLab issue with a local Ollama model."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

try:
    from .env_config import get_env, load_project_env
except ImportError:
    from env_config import get_env, load_project_env  # type: ignore

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_TIMEOUT = 600
ANALYSIS_MARKER = "<!-- issue_analysis:auto -->"

SYSTEM_PROMPT = """あなたは GitLab issue を分析して、開発チームがすぐ動ける短く実務的な Markdown コメントを書くアシスタントです。

次のルールを守ってください。
- 出力は日本語の Markdown のみ
- 推測は最小限にし、根拠が弱い点は「不明点・要確認事項」に回す
- 事実として書けるのは入力 JSON に含まれる情報だけ
- コードブロックは使わない
- 先頭は次の1行を使う:
> 🤖 **/issue-analysis by Ollama ({model})** — このコメントはローカルモデルによる自動分析です。内容は参考情報として扱ってください。
- 次の見出しをこの順番で必ず含める:
## 依頼内容の要約
## タスク分解
## カテゴリ分類・優先度・工数
## 不明点・要確認事項
- 「タスク分解」は Markdown のチェックリストにする
- 「カテゴリ分類・優先度・工数」では以下の3項目を箇条書きにする:
  - カテゴリ
  - 優先度
  - 工数
"""


def parse_args() -> argparse.Namespace:
    load_project_env()
    default_host = get_env("OLLAMA_HOST", DEFAULT_HOST) or DEFAULT_HOST
    default_model = get_env("OLLAMA_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--issue-json",
        default="issue.json",
        help="input issue JSON path (default: ./issue.json)",
    )
    ap.add_argument(
        "--out",
        default="analysis.md",
        help="output Markdown path (default: ./analysis.md)",
    )
    ap.add_argument(
        "--model",
        default=default_model,
        help=f"Ollama model name (default: {default_model})",
    )
    ap.add_argument(
        "--host",
        default=default_host,
        help=f"Ollama API base URL (default: {default_host})",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"request timeout seconds (default: {DEFAULT_TIMEOUT})",
    )
    return ap.parse_args()


def load_issue(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("issue JSON must be an object")
    return data


def build_messages(model: str, issue: dict[str, Any]) -> list[dict[str, str]]:
    rendered_issue = json.dumps(issue, ensure_ascii=False, indent=2)
    system_prompt = SYSTEM_PROMPT.format(model=model)
    user_prompt = (
        "以下は GitLab issue と関連コメントの JSON です。"
        "内容を分析し、指定フォーマットどおりに Markdown コメントを作成してください。\n\n"
        f"{rendered_issue}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def strip_thinking(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def normalize_analysis_markdown(text: str) -> str:
    cleaned = strip_thinking(text)
    if cleaned.startswith(ANALYSIS_MARKER):
        return cleaned
    return f"{ANALYSIS_MARKER}\n{cleaned}".strip()


def is_analysis_comment(text: str) -> bool:
    stripped = (text or "").strip()
    return stripped.startswith(ANALYSIS_MARKER) or "/issue-analysis by Ollama" in stripped


def chat(host: str, model: str, messages: list[dict[str, str]], timeout: int) -> str:
    response = requests.post(
        f"{host.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": 0.2,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    content = ((payload.get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("Ollama returned an empty response")
    return content


def generate_analysis(issue: dict[str, Any], model: str, host: str, timeout: int) -> str:
    return normalize_analysis_markdown(
        chat(
            host=host,
            model=model,
            messages=build_messages(model, issue),
            timeout=timeout,
        )
    )


def main() -> int:
    args = parse_args()

    try:
        issue = load_issue(args.issue_json)
    except FileNotFoundError:
        print(f"issue JSON not found: {args.issue_json}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as e:
        print(f"failed to load issue JSON: {e}", file=sys.stderr)
        return 2

    try:
        content = generate_analysis(
            issue=issue,
            model=args.model,
            host=args.host,
            timeout=args.timeout,
        )
    except requests.HTTPError as e:
        body = e.response.text[:400] if e.response is not None else ""
        print(f"Ollama API error: {e} body={body}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"Ollama request failed: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"Ollama response error: {e}", file=sys.stderr)
        return 3

    out_path = Path(args.out)
    out_path.write_text(content + "\n", encoding="utf-8")
    print(f"wrote {out_path}: model={args.model!r}, chars={len(content)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
