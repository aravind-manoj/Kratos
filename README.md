# Kratos

Autonomous pentesting with Docker sub-agents and a live terminal dashboard.

Kratos is a standalone CLI rewrite inspired by the concept of [hacker-ai](https://github.com/aravind-manoj/hacker-ai). It is not a code fork of that repository — only the core idea (coordinator + Docker sub-agents for autonomous pentesting) carries over.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop / Docker daemon running
- Groq API key

## Setup

```bash
cd cli
cp .env.example .env
# Edit .env and set GROQ_API_KEY
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
```

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
