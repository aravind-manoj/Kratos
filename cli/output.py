import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from cli.orchestrator import ScanResult

console = Console()

SEVERITY_STYLE = {
  "critical": "bold red",
  "high": "red",
  "medium": "yellow",
  "low": "green",
}

def print_summary(result: ScanResult) -> None:
  console.print()
  console.print(Panel(f"[bold]Scan complete[/bold] — status: {result.status}", expand=False))
  console.print(f"[bold]Targets:[/bold] {', '.join(result.targets)}")

  if result.summary:
    console.print(Panel(result.summary, title="Summary", border_style="blue"))

  findings = result.findings or []
  if not findings:
    console.print("[dim]No structured findings were finalized.[/dim]")
    for sub in result.subagents:
      if sub.get("findings"):
        console.print(f"\n[bold]{sub['id']}[/bold]:")
        for f in sub["findings"]:
          console.print(f"  • {f}")
    return

  for item in findings:
    severity = str(item.get("severity", ""))
    title = str(item.get("title", "Finding"))
    style = SEVERITY_STYLE.get(severity.lower(), "white")
    console.print(f"\n[{style}]{severity.upper()}: {title}[/{style}]")
    if item.get("description"):
      console.print(f"  {item['description']}")
    if item.get("evidence"):
      console.print(f"  [dim]Evidence:[/dim] {item['evidence']}")
    if item.get("remediation"):
      console.print(f"  [dim]Fix:[/dim] {item['remediation']}")


def write_json(result: ScanResult, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
  console.print(f"[green]Results written to[/green] {path}")
