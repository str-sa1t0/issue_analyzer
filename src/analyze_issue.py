#!/usr/bin/env python3
"""Analyze a fetched GitLab issue with a configurable inference backend."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    from .env_config import get_env, load_project_env
except ImportError:
    from env_config import get_env, load_project_env  # type: ignore

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_TIMEOUT = 600
ANALYSIS_MARKER = "<!-- issue_analysis:auto -->"
OPENAI_COMPATIBLE_STYLES = {
    "openai",
    "openai-compatible",
    "openai_compatible",
    "compatible",
    "openwebui",
    "open-webui",
}

SYSTEM_PROMPT = """あなたは GitLab issue を分析して、開発チームがすぐ動ける短く実務的な Markdown コメントを書くアシスタントです。

次のルールを守ってください。
- 出力は日本語の Markdown のみ
- 推測は最小限にし、根拠が弱い点は「不明点・要確認事項」に回す
- 事実として書けるのは入力 JSON に含まれる情報だけ
- コードブロックは使わない
- 先頭は次の1行を使う:
> 🤖 **/issue-analysis by {provider} ({model})** — このコメントは自動分析です。内容は参考情報として扱ってください。
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


@dataclass(frozen=True)
class InferenceConfig:
    api_style: str
    base_url: str
    model: str
    api_key: str | None
    provider_label: str


def normalize_api_style(style: str | None) -> str:
    normalized = (style or "ollama").strip().lower()
    if normalized == "ollama":
        return "ollama"
    if normalized in OPENAI_COMPATIBLE_STYLES:
        return "openai-compatible"
    raise ValueError(f"unsupported api style: {style!r}")


def default_provider_label(raw_style: str | None, normalized_style: str) -> str:
    raw = (raw_style or "").strip().lower()
    if raw in {"openwebui", "open-webui"}:
        return "OpenWebUI"
    if normalized_style == "ollama":
        return "Ollama"
    return "OpenAI-compatible"


def load_inference_config(
    api_style: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> InferenceConfig:
    load_project_env()
    raw_style = api_style or get_env("LLM_API_STYLE") or "ollama"
    normalized_style = normalize_api_style(raw_style)
    resolved_base_url = (base_url or get_env("LLM_BASE_URL") or DEFAULT_OLLAMA_HOST).strip()
    resolved_model = (model or get_env("LLM_MODEL") or DEFAULT_MODEL).strip()
    resolved_api_key = (api_key or get_env("LLM_API_KEY") or "").strip() or None
    provider_label = (
        get_env("LLM_PROVIDER_LABEL")
        or default_provider_label(raw_style, normalized_style)
    )
    return InferenceConfig(
        api_style=normalized_style,
        base_url=resolved_base_url,
        model=resolved_model,
        api_key=resolved_api_key,
        provider_label=provider_label,
    )


def build_chat_url(config: InferenceConfig) -> str:
    base = config.base_url.rstrip("/")
    if config.api_style == "ollama":
        return base if base.endswith("/api/chat") else f"{base}/api/chat"
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def parse_args() -> argparse.Namespace:
    config = load_inference_config()
    default_api_style = get_env("LLM_API_STYLE") or config.api_style
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
        default=config.model,
        help=f"model name (default: {config.model})",
    )
    ap.add_argument(
        "--host",
        default=config.base_url,
        help=f"inference API base URL (default: {config.base_url})",
    )
    ap.add_argument(
        "--api-style",
        default=default_api_style,
        help="inference API style: ollama, openai-compatible, or openwebui",
    )
    ap.add_argument(
        "--api-key",
        default=config.api_key,
        help="optional bearer token for OpenAI-compatible endpoints",
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


def build_messages(config: InferenceConfig, issue: dict[str, Any]) -> list[dict[str, str]]:
    rendered_issue = json.dumps(issue, ensure_ascii=False, indent=2)
    system_prompt = SYSTEM_PROMPT.format(
        provider=config.provider_label,
        model=config.model,
    )
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
    return stripped.startswith(ANALYSIS_MARKER) or "/issue-analysis by " in stripped


def extract_text_from_openai_message(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def extract_chat_content(config: InferenceConfig, payload: dict[str, Any]) -> str:
    if config.api_style == "ollama":
        return str(((payload.get("message") or {}).get("content") or "")).strip()

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message") or {}
    if not isinstance(message, dict):
        return ""
    return extract_text_from_openai_message(message.get("content"))


def build_request_payload(
    config: InferenceConfig,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    if config.api_style == "ollama":
        return {
            "model": config.model,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": 0.2,
            },
        }
    return {
        "model": config.model,
        "stream": False,
        "messages": messages,
        "temperature": 0.2,
    }


def build_request_headers(config: InferenceConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_style != "ollama" and config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def chat(config: InferenceConfig, messages: list[dict[str, str]], timeout: int) -> str:
    response = requests.post(
        build_chat_url(config),
        headers=build_request_headers(config),
        json=build_request_payload(config, messages),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("inference response is not a JSON object")
    content = extract_chat_content(config, payload)
    if not content:
        raise ValueError("inference backend returned an empty response")
    return content


def generate_analysis(
    issue: dict[str, Any],
    model: str,
    host: str,
    timeout: int,
    api_style: str | None = None,
    api_key: str | None = None,
) -> str:
    config = load_inference_config(
        api_style=api_style,
        base_url=host,
        model=model,
        api_key=api_key,
    )
    return normalize_analysis_markdown(
        chat(
            config=config,
            messages=build_messages(config, issue),
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
            api_style=args.api_style,
            api_key=args.api_key,
        )
    except requests.HTTPError as e:
        body = e.response.text[:400] if e.response is not None else ""
        print(f"Inference API error: {e} body={body}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"Inference request failed: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"Inference response error: {e}", file=sys.stderr)
        return 3

    out_path = Path(args.out)
    out_path.write_text(content + "\n", encoding="utf-8")
    print(f"wrote {out_path}: model={args.model!r}, chars={len(content)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
