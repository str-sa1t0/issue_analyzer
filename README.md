# issue_analysis

`uv` と Python 3.14 で管理する小さな CLI ツール集です。

## セットアップ

```bash
uv python install 3.14
uv sync
```

## 実行例

```bash
uv run python -m src.parse_url "group/project#42"
uv run python -m src.fetch_issue --url "https://gitlab.example.com/group/project/-/issues/42"
uv run python -m src.analyze_issue --issue-json issue.json --model gemma4:26b
uv run python -m src.post_comment --url "https://gitlab.example.com/group/project/-/issues/42" --body-file comment.md
uv run python -m src.process_analyze_label --label analyze --processed-label analyzed
uv run python -m src.process_analyze_label --label analyze --processed-label analyzed --artifacts-dir runs
```

必要な環境変数:

- `GITLAB_TOKEN`
- `GITLAB_URL`
- `GITLAB_PROJECT_ID` または `GITLAB_PROJECT`

`src.analyze_issue` は `ollama` ネイティブ API と OpenAI-compatible API の両方に対応しています。既定値は `LLM_API_STYLE=ollama`、`LLM_BASE_URL=http://127.0.0.1:11434`、モデルは `gemma4:26b` です。

`.env` も自動で読み込みます。GitLab トークンは正規名の `GITLAB_TOKEN` を推奨しますが、既存の `GitLabToken` と `GLToken` も互換で受け付けます。推論設定も `LLM_*` を正規名として扱い、既存の `OLLAMA_HOST` / `OLLAMA_MODEL` は後方互換で受け付けます。

OpenWebUI の OpenAI-compatible endpoint を使う場合の例:

```bash
LLM_API_STYLE=openwebui
LLM_BASE_URL=http://localhost:3000/api
LLM_API_KEY=YOUR_OPEN_WEBUI_API_KEY
LLM_MODEL=gemma4:26b
```

この設定では `POST /api/chat/completions` を使います。一般的な OpenAI-compatible サーバーを使う場合は `LLM_API_STYLE=openai-compatible` とし、`LLM_BASE_URL` に `/v1` まで含めたベース URL を指定してください。

`src.process_analyze_label` は、`analyze` ラベル付きの Issue / Work Item を一覧取得し、`fetch -> analyze -> post_comment` を実行します。成功時は `analyze` を外して `analyzed` を付けるので、同じアイテムの再処理を避けやすくしています。既定では `analysis.md` や `issue.json` のようなアーティファクトは保存しません。必要なときだけ `--artifacts-dir runs` を付けて保存できます。`--interval 60` のように指定するとポーリング運用もできます。
