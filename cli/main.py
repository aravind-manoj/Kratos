import webbrowser
from pathlib import Path
from typing import Optional
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from cli.core.llm import LLMProviderError, resolve_provider
from cli.core.live_state import LiveState
from cli.orchestrator import PentestOrchestrator
from cli.output import print_summary, write_json
from cli.web.server import DashboardServer

load_dotenv()

console = Console()

APP_HELP = """
Kratos — autonomous pentest with Docker sub-agents and a live terminal dashboard.

Usage:
  kratos scan TARGET [TARGET...] [OPTIONS]

Arguments:
  TARGET    IP, hostname, or URL. Pass multiple targets or comma-separated values.

Options:
  -v, --vectors TEXT         Comma-separated attack vectors
                             (default: port-scan,service-enumeration,web-scan)
  -n, --note TEXT            Free-text instructions for the coordinator agent
  -o, --output PATH          Write structured JSON results to this file
  --image TEXT               Docker image for sub-agents (default: ubuntu:latest)
  --max-iterations INTEGER   Main agent loop cap (default: 50)
  --port INTEGER             Live dashboard port (default: 8765)
  --no-browser               Do not auto-open the dashboard in a browser
  --no-ui                    Headless mode — skip the web dashboard
  --provider TEXT            LLM provider: openai, anthropic, google,
                             openrouter, groq (auto-detects from env if omitted)

Environment:
  LLM_PROVIDER               Force provider when multiple API keys are set
  LLM_MAIN_MODEL             Override coordinator model
  LLM_SUB_MODEL              Override sub-agent model
  OPENAI_API_KEY             OpenAI API key
  ANTHROPIC_API_KEY          Anthropic API key
  GOOGLE_API_KEY             Google AI Studio / Gemini API key
  GEMINI_API_KEY             Alias for Google AI Studio key
  OPENROUTER_API_KEY         OpenRouter API key
  OPENROUTER_BASE_URL        OpenRouter API base (default: openrouter.ai/api/v1)
  GROQ_API_KEY               Groq API key

Examples:
  kratos scan 192.168.1.1
  kratos scan 10.0.0.5 https://example.com -v port-scan,web-scan
  kratos scan example.com --note "lab only" -o results/findings.json
  kratos scan 192.168.1.1 --no-ui --port 9000
""".strip()

app = typer.Typer(
  name="kratos",
  help=APP_HELP,
  no_args_is_help=True,
  add_completion=False,
)

AUTHORIZATION_WARNING = """
[bold red]Authorization Required[/bold red]

Only scan systems you own or have explicit written permission to test.
Unauthorized access is illegal.
"""

@app.callback()
def main():
  """Autonomous pentest CLI. Run `kratos scan --help` for option details."""

@app.command("scan")
def scan(
  targets: list[str] = typer.Argument(..., help="Target IP(s) or URL(s)"),
  vectors: str = typer.Option(
    "port-scan,service-enumeration,web-scan",
    "--vectors",
    "-v",
    help="Comma-separated attack vectors",
  ),
  note: str = typer.Option("", "--note", "-n", help="Instructions for the main agent"),
  output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write JSON results to file"),
  image: str = typer.Option("ubuntu:latest", "--image", help="Default Docker image for sub-agents"),
  max_iterations: int = typer.Option(50, "--max-iterations", help="Main agent loop cap"),
  port: int = typer.Option(8765, "--port", help="Live dashboard port"),
  no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
  no_ui: bool = typer.Option(False, "--no-ui", help="Headless mode — no web dashboard"),
  provider: Optional[str] = typer.Option(
    None,
    "--provider",
    help="LLM provider: openai, anthropic, google, openrouter, groq (auto-detects from env if omitted)",
  ),
):
  """Run an autonomous pentest against the given target(s).

  Targets can be IPs, hostnames, or URLs. Use --vectors to suggest attack
  approaches, --note for custom instructions, and --output to save JSON results.

  By default a live dashboard starts at http://127.0.0.1:8765 with real-time
  sub-agent terminals. Use --no-ui for headless runs or --no-browser to skip
  opening a browser tab.
  """
  try:
    selected_provider = resolve_provider(provider)
  except LLMProviderError as e:
    console.print(f"[red]{e}[/red]")
    raise typer.Exit(1)

  console.print(Panel(AUTHORIZATION_WARNING.strip(), border_style="red"))
  console.print(f"[dim]LLM provider:[/dim] {selected_provider}\n")
  target_list = []
  for t in targets:
    target_list.extend([x.strip() for x in t.split(",") if x.strip()])

  if not target_list:
    console.print("[red]At least one target is required.[/red]")
    raise typer.Exit(1)

  vector_list = [v.strip() for v in vectors.split(",") if v.strip()]

  live_state = LiveState()
  dashboard: DashboardServer | None = None

  if not no_ui:
    dashboard = DashboardServer(live_state, port=port)
    try:
      dashboard.start()
    except (OSError, TimeoutError) as e:
      console.print(f"[red]Could not start dashboard on port {port}: {e}[/red]")
      raise typer.Exit(1)

    console.print(f"[bold green]Live dashboard:[/bold green] {dashboard.url}")
    if not no_browser:
      webbrowser.open(dashboard.url)

  console.print(f"[bold]Starting scan against[/bold] {', '.join(target_list)}")
  console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

  orchestrator = PentestOrchestrator(
    live_state=live_state,
    default_image=image,
    max_iterations=max_iterations,
    provider=selected_provider,
  )

  try:
    result = orchestrator.run(target_list, vector_list, note)
  finally:
    if dashboard:
      dashboard.stop()

  print_summary(result)

  if output:
    write_json(result, output)

  if result.stopped_by_user:
    raise typer.Exit(130)
  if result.status == "max_iterations":
    raise typer.Exit(2)

if __name__ == "__main__":
  app()