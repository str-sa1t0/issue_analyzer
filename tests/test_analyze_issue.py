from __future__ import annotations

import unittest

from src.analyze_issue import (
    InferenceConfig,
    build_chat_url,
    extract_chat_content,
    normalize_api_style,
)


class AnalyzeIssueTests(unittest.TestCase):
    def test_normalize_api_style_accepts_openwebui_alias(self) -> None:
        self.assertEqual(normalize_api_style("openwebui"), "openai-compatible")
        self.assertEqual(normalize_api_style("openai-compatible"), "openai-compatible")
        self.assertEqual(normalize_api_style("ollama"), "ollama")

    def test_build_chat_url_for_ollama(self) -> None:
        config = InferenceConfig(
            api_style="ollama",
            base_url="http://127.0.0.1:11434",
            model="gemma4:26b",
            api_key=None,
            provider_label="Ollama",
        )
        self.assertEqual(build_chat_url(config), "http://127.0.0.1:11434/api/chat")

    def test_build_chat_url_for_openwebui_api_base(self) -> None:
        config = InferenceConfig(
            api_style="openai-compatible",
            base_url="http://localhost:3000/api",
            model="gemma4:26b",
            api_key="sk-test",
            provider_label="OpenWebUI",
        )
        self.assertEqual(
            build_chat_url(config),
            "http://localhost:3000/api/chat/completions",
        )

    def test_extract_chat_content_for_openai_compatible_response(self) -> None:
        config = InferenceConfig(
            api_style="openai-compatible",
            base_url="http://localhost:3000/api",
            model="gemma4:26b",
            api_key="sk-test",
            provider_label="OpenWebUI",
        )
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "analysis body",
                    }
                }
            ]
        }
        self.assertEqual(extract_chat_content(config, payload), "analysis body")


if __name__ == "__main__":
    unittest.main()
