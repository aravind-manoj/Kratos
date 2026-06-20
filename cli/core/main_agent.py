import threading
from uuid import uuid4

from langchain_core.tools import tool

from cli.core.live_state import LiveState
from cli.core.llm import create_main_llm
from cli.core.logger import log_info
from cli.core.prompts import MAIN_AGENT_PROMPT
from cli.core.react_loop import ReactLoop
from cli.core.sub_agent import SubAgent, format_subagent_report


class MainAgent:
  def __init__(
    self,
    live_state: LiveState,
    subagents: dict[str, SubAgent],
    stop_event: threading.Event,
    default_image: str = "ubuntu:latest",
    provider: str | None = None,
  ):
    self.live_state = live_state
    self.subagents = subagents
    self.stop_event = stop_event
    self.default_image = default_image
    self.provider = provider
    self.finalized_payload: dict | None = None
    self.loop = ReactLoop(
      create_main_llm(provider),
      self._build_tools(),
      MAIN_AGENT_PROMPT,
      agent_id="main",
    )

  def _build_tools(self) -> list:
    subagents = self.subagents
    live_state = self.live_state
    stop_event = self.stop_event
    default_image = self.default_image
    agent = self

    @tool("create_subagent")
    def create_subagent(task: str, image: str = default_image) -> str:
      """Create a new sub-agent with its own Docker container for a specific task."""
      try:
        subagent_id = f"subagent-{uuid4()}"
        sub = SubAgent(subagent_id, task, live_state, image=image, provider=agent.provider)
        sub.start()
        subagents[subagent_id] = sub
        return f"Sub-agent '{subagent_id}' created and started.\nTask:\n{task}"
      except Exception as e:
        return f"Error creating sub-agent: {e}"

    @tool("send_message")
    def send_message(subagent_id: str, message: str) -> str:
      """Send guidance or instructions to a running sub-agent."""
      sub = subagents.get(subagent_id)
      if not sub:
        return f"Error: Sub-agent '{subagent_id}' not found."
      sub.send_message(message)
      return f"Message sent to {subagent_id}: {message}"

    @tool("check_subagent_status")
    def check_subagent_status(subagent_id: str) -> str:
      """Check sub-agent status, completed steps, and findings."""
      sub = subagents.get(subagent_id)
      if not sub:
        return f"Error: Sub-agent '{subagent_id}' not found."
      return format_subagent_report(subagent_id, sub)

    @tool("get_subagent_findings")
    def get_subagent_findings(subagent_id: str) -> str:
      """Get all findings from a completed or stopped sub-agent."""
      sub = subagents.get(subagent_id)
      if not sub:
        return f"Error: Sub-agent '{subagent_id}' not found."
      return format_subagent_report(subagent_id, sub, findings_only=True)

    @tool("list_subagents")
    def list_subagents() -> str:
      """List all sub-agents with their ID and assigned task."""
      if not subagents:
        return "No sub-agents have been created."
      lines = [f"- **{sid}**:\n{sub.task}" for sid, sub in subagents.items()]
      return "Sub-agents:\n" + "\n".join(lines)

    @tool("stop_subagent")
    def stop_subagent(subagent_id: str) -> str:
      """Forcefully stop a sub-agent and its Docker container."""
      sub = subagents.get(subagent_id)
      if not sub:
        return f"Error: Sub-agent '{subagent_id}' not found."
      sub.stop()
      return f"Sub-agent '{subagent_id}' stopped."

    @tool("finalize_findings")
    def finalize_findings(
      summary: str,
      findings: list[dict],
      target: str = "Unknown Target",
    ) -> str:
      """Submit final structured findings and complete the assessment."""
      agent.finalized_payload = {
        "target": target,
        "summary": summary,
        "findings": findings,
      }
      log_info(f"Findings finalized for {target}", agent_id="main")
      return "Findings recorded. Assessment complete."

    @tool("wait")
    def wait(seconds: int) -> str:
      """Wait for sub-agents to make progress."""
      log_info(f"Waiting {seconds}s", agent_id="main")
      stop_event.wait(seconds)
      if stop_event.is_set():
        raise InterruptedError("Main agent stopped")
      return f"Waited for {seconds} seconds."

    return [
      create_subagent,
      send_message,
      check_subagent_status,
      get_subagent_findings,
      list_subagents,
      stop_subagent,
      finalize_findings,
      wait,
    ]

  def run_turn(self, nudge: str | None = None):
    return self.loop.run_turn(nudge=nudge, stop_event=self.stop_event)

  @property
  def finalized(self) -> bool:
    return self.finalized_payload is not None
