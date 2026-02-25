# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Arena2API is a Python FastAPI proxy that exposes arena.ai's 300+ AI models through an OpenAI-compatible API. See `README.md` for full architecture and usage docs.

### Running the server

```bash
python server.py
```

Starts on port 9090 by default (override with `PORT` env var). Set `DEBUG=1` for verbose logging.

### Key endpoints

| Endpoint | Description |
|---|---|
| `GET /health` or `GET /` | Health check + extension status |
| `GET /v1/models` | List available models (OpenAI format) |
| `POST /v1/chat/completions` | Chat completions (stream/non-stream) |
| `POST /v1/extension/push` | Extension pushes tokens/cookies/models |
| `GET /v1/extension/status` | Extension connection status |

### Development notes

- **No automated tests or linter** are configured in this project. The codebase is a single `server.py` file with browser extensions in `extension/` (Chrome) and `extension-firefox/` (Firefox).
- **Full E2E testing** requires a real browser with the extension loaded and an active arena.ai session — this is not possible in a headless cloud environment.
- **Local testing without extension:** The server starts fine without a connected extension. You can simulate extension pushes via `POST /v1/extension/push` with mock data to test the API flow. Example:
  ```bash
  curl -X POST http://localhost:9090/v1/extension/push \
    -H "Content-Type: application/json" \
    -d '{"cookies":{"arena-user-id":"test"},"auth_token":"test","models":[{"publicName":"GPT-4o","id":"gpt-4o","capabilities":{"outputCapabilities":["text"],"inputCapabilities":["text"]}}],"v3_tokens":[{"token":"fake-token-at-least-20-chars-long","action":"chat_submit","age_ms":0}]}'
  ```
- **pip install location:** Dependencies install to `~/.local` (user site-packages). The `~/.local/bin` directory may need to be on `PATH` for `uvicorn`/`fastapi` CLI tools, though `python server.py` works without this.
- **Browser extensions** are plain JavaScript — no build step required.
