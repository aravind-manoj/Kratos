# Kratos

Autonomous pentesting with Docker sub-agents and a live terminal dashboard.

Kratos is a standalone CLI rewrite inspired by the concept of [hacker-ai](https://github.com/aravind-manoj/hacker-ai). It is not a code fork of that repository — only the core idea (coordinator + Docker sub-agents for autonomous pentesting) carries over.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop / Docker daemon running
- An LLM API key (Groq, OpenAI, Anthropic, or Google AI Studio)

## Setup

```bash
cd cli
cp .env.example .env
# Edit .env and set an API key for your chosen provider
uv sync
```

## Usage

```bash
# Run a scan (opens live dashboard at http://127.0.0.1:8765)
uv run kratos scan 192.168.1.1

# Multiple targets, custom vectors, JSON output
uv run kratos scan 10.0.0.5,https://example.com \
  --vectors "port scan,web scan" \
  --note "lab environment only" \
  --output results/findings.json

# Headless (no web UI)
uv run kratos scan 192.168.1.1 --no-ui -o findings.json

# Custom dashboard port
uv run kratos scan example.com --port 9000 --no-browser

# Pick LLM provider explicitly
uv run kratos scan 192.168.1.1 --provider openai
uv run kratos scan 192.168.1.1 --provider anthropic
uv run kratos scan 192.168.1.1 --provider openrouter
```

## LLM providers

Kratos auto-detects the provider from your environment. Set **one** API key, or set `LLM_PROVIDER` / `--provider` when multiple keys are present. Auto-detect priority: **openai → anthropic → google → openrouter → groq**.

| Provider | Env key(s) | Default models (main / sub) |
|----------|------------|-----------------------------|
| `openai` | `OPENAI_API_KEY` | gpt-5-mini / gpt-5.5 (1M context) |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-haiku-4-5 / claude-sonnet-4-6 |
| `google` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | gemini-3.1-flash-lite / gemini-3.1-pro-preview |
| `openrouter` | `OPENROUTER_API_KEY` | claude-sonnet-4.6 / claude-opus-4.6 (1M context, cyber-focused) |
| `groq` | `GROQ_API_KEY` | openai/gpt-oss-20b / openai/gpt-oss-120b |

Override models with `LLM_MAIN_MODEL` and `LLM_SUB_MODEL`.

## Live Dashboard

When a scan starts, a local FastAPI server serves a dashboard with:

- Per sub-agent status, completed steps, and findings
- Live xterm.js terminal output from each Docker sandbox
- WebSocket updates (~500ms refresh)

Press **Ctrl+C** in the terminal to stop the scan and clean up containers.

## Authorization

Only scan systems you own or have explicit written permission to test.

## License & contributing

Kratos is **open source**. You are free to use, modify, and contribute to this project.

Contributions are welcome — open an issue or pull request if you want to improve Kratos.

Licensed under the MIT License.
