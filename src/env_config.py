#!/usr/bin/env python3
"""Project-local environment loading helpers."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "GITLAB_TOKEN": ("GitLabToken", "GLToken"),
    "GITLAB_URL": ("GitLabUrl", "GLUrl"),
    "GITLAB_PROJECT": ("GitLabProject", "GLProject"),
    "GITLAB_PROJECT_ID": ("GitLabProjectId", "GLProjectId"),
    "OLLAMA_HOST": ("OllamaHost",),
    "OLLAMA_MODEL": ("OllamaModel",),
}

_LOADED = False


def _normalize_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_gitlab_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    if not parsed.scheme or not parsed.netloc:
        return raw.strip().rstrip("/")

    path = parsed.path.rstrip("/")
    api_marker = "/api/v4"
    if api_marker in path:
        path = path.split(api_marker, 1)[0]
    else:
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2:
            path = ""

    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    return normalized.rstrip("/")


def load_project_env() -> None:
    global _LOADED
    if _LOADED:
        return

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key.removeprefix("export ").strip()
            if not key:
                continue
            os.environ.setdefault(key, _normalize_value(raw_value))

    for canonical, aliases in ENV_ALIASES.items():
        if os.environ.get(canonical):
            continue
        for alias in aliases:
            if os.environ.get(alias):
                os.environ[canonical] = os.environ[alias]
                break

    if os.environ.get("GITLAB_URL"):
        os.environ["GITLAB_URL"] = _normalize_gitlab_url(os.environ["GITLAB_URL"])

    _LOADED = True


def get_env(name: str, default: str | None = None) -> str | None:
    load_project_env()
    return os.environ.get(name, default)


def get_gitlab_project_ref() -> str | None:
    load_project_env()
    return os.environ.get("GITLAB_PROJECT_ID") or os.environ.get("GITLAB_PROJECT")
