import queue
import threading
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from cli.core.docker_controller import Controller
from cli.core.live_state import LiveState
from cli.core.llm import create_sub_llm
from cli.core.logger import log_error, log_info, log_warn
from cli.core.prompts import SUB_AGENT_PROMPT
from cli.core.react_loop import ReactLoop

_KEY_MAP = {
  "enter": "\n",
  "return": "\n",
  "tab": "\t",
  "backspace": "\x7f",
  "escape": "\x1b",
  "esc": "\x1b",
  "ctrl+c": "\x03",
  "ctrl+d": "\x04",
  "ctrl+z": "\x1a",
  "ctrl+l": "\x0c",
  "ctrl+a": "\x01",
  "ctrl+e": "\x05",
  "ctrl+u": "\x15",
  "ctrl+k": "\x0b",
  "ctrl+w": "\x17",
  "up": "\x1b[A",
  "down": "\x1b[B",
  "right": "\x1b[C",
  "left": "\x1b[D",
  "space": " ",
}


def _translate_keys(raw: str) -> str:
  return "".join(_KEY_MAP.get(t.lower(), t) for t in raw.split())


def _drain_queue(msg_queue: queue.Queue) -> list[str]:
  items: list[str] = []
  while not msg_queue.empty():
    try:
      items.append(msg_queue.get_nowait())
    except queue.Empty:
      break
  return items


def format_subagent_report(
  subagent_id: str,
  sub: "SubAgent",
  *,
  findings_only: bool = False,
) -> str:
  findings = sub.get_findings()
  summary = sub.get_summary()

  if findings_only:
    result = f"--- Findings from {subagent_id} ---\n"
    if findings:
      for i, f in enumerate(findings, 1):
        result += f"  {i}. {f}\n"
    else:
      result += "  No findings reported yet.\n"
    if summary:
      result += f"\n  Summary: {summary}\n"
    return result

  steps = sub.get_completed_steps()
  result = f"Sub-agent '{subagent_id}':\n  Status: {sub.get_status()}\n"
  if steps:
    result += f"  Completed Steps ({len(steps)}):\n"
    for i, step in enumerate(steps, 1):
      result += f"    {i}. {step}\n"
  else:
    result += "  Completed Steps: None yet\n"

  if findings:
    result += f"  Findings ({len(findings)}):\n"
    for i, f in enumerate(findings, 1):
      result += f"    {i}. {f}\n"
  else:
    result += "  Findings: None yet\n"
  return result


class TerminalTracker:
  def __init__(self):
    self._last_snapshot = ""
    self._consecutive_stale = 0

  def update(self, current_screen: str) -> bool:
    if current_screen == self._last_snapshot:
      self._consecutive_stale += 1
      return self._consecutive_stale >= 2
    self._last_snapshot = current_screen
    self._consecutive_stale = 0
    return False


class SubAgent:
  MAX_ITERATIONS = 30

  def __init__(
    self,
    subagent_id: str,
    task: str,
    live_state: LiveState,
    image: str = "ubuntu:latest",
    provider: str | None = None,
  ):
    self.id = subagent_id
    self.task = task
    self.image = image
    self.live_state = live_state
    self.state: dict = {
      "status": "starting",
      "completed_steps": [],
      "findings": [],
      "summary": None,
    }
    self.messages: queue.Queue = queue.Queue()
    self.stop_event = threading.Event()

    self.controller = Controller(
      image,
      tag=subagent_id,
      on_buffer_update=lambda buf: live_state.update_buffer(subagent_id, buf),
    )
    self._ctx = {
      "controller": self.controller,
      "messages": self.messages,
      "state": self.state,
      "subagent_id": subagent_id,
      "terminal_tracker": TerminalTracker(),
      "stop_event": self.stop_event,
    }
    self.loop = ReactLoop(
      create_sub_llm(provider),
      self._build_tools(),
      SUB_AGENT_PROMPT,
      agent_id=subagent_id,
    )

  def _sync_live_state(self):
    self.live_state.update_subagent(
      self.id,
      status=self.state["status"],
      completed_steps=self.state["completed_steps"],
      findings=self.state["findings"],
      summary=self.state["summary"],
    )

  def _check_stopped(self):
    if self.stop_event.is_set():
      raise InterruptedError("Sub-agent stopped")

  def _build_tools(self) -> list:
    ctx = self._ctx

    @tool("execute_command")
    def execute_command(command: str) -> str:
      """Execute a shell command in the Docker container."""
      self._check_stopped()
      ctx["controller"].send_command(command)
      ctx["stop_event"].wait(1.0)
      log_info(f"Command: {command}", agent_id=ctx["subagent_id"])
      return f"Command sent: {command}"

    @tool("read_terminal")
    def read_terminal(last_chars: int = 5000) -> str:
      """Read recent terminal output from the Docker container."""
      self._check_stopped()
      screen = ctx["controller"].get_screen(max(2000, last_chars))
      is_stale = ctx["terminal_tracker"].update(screen)
      result = f"--- Terminal Output ---\n{screen}"
      if is_stale:
        result += (
          "\n\nNOTE: Terminal output is IDENTICAL to your previous read. "
          "Call `wait_for_output` before reading again."
        )
      return result

    @tool("wait_for_output")
    def wait_for_output(seconds: int = 5) -> str:
      """Wait before reading terminal again when output hasn't changed."""
      seconds = max(5, min(60, seconds))
      log_info(f"Waiting {seconds}s for output", agent_id=ctx["subagent_id"])
      ctx["stop_event"].wait(seconds)
      self._check_stopped()
      return f"Waited {seconds} seconds. Read the terminal again."

    @tool("send_keys")
    def send_keys(keys: str) -> str:
      """Send keystrokes to the terminal (e.g. 'y Enter', 'Ctrl+C')."""
      self._check_stopped()
      ctx["controller"].send_keys(_translate_keys(keys))
      return f"Keys sent: {repr(keys)}"

    @tool("check_messages")
    def check_messages() -> str:
      """Check for new messages from the main agent."""
      self._check_stopped()
      pending = _drain_queue(ctx["messages"])
      if pending:
        return "Messages from main agent:\n" + "\n".join(f"  - {m}" for m in pending)
      return "No new messages from the main agent."

    @tool("mark_step_completed")
    def mark_step_completed(step_description: str) -> str:
      """Mark a step as completed."""
      self._check_stopped()
      ctx["state"]["completed_steps"].append(step_description)
      self._sync_live_state()
      log_info(f"Step completed: {step_description}", agent_id=ctx["subagent_id"])
      return f"Step marked as completed: {step_description}"

    @tool("report_finding")
    def report_finding(finding: str) -> str:
      """Report a finding discovered during the task."""
      self._check_stopped()
      ctx["state"]["findings"].append(finding)
      self._sync_live_state()
      log_info(f"Finding: {finding}", agent_id=ctx["subagent_id"])
      return f"Finding recorded: {finding}"

    @tool("report_to_main")
    def report_to_main(summary: str) -> str:
      """Signal task completion with a summary."""
      self._check_stopped()
      ctx["state"]["summary"] = summary
      ctx["state"]["status"] = "completed"
      self._sync_live_state()
      return "Task completion reported. Your task is now complete."

    return [
      execute_command,
      read_terminal,
      wait_for_output,
      send_keys,
      check_messages,
      mark_step_completed,
      report_finding,
      report_to_main,
    ]

  def start(self):
    self.live_state.register_subagent(self.id, self.task)
    self.controller.start()
    threading.Thread(target=self._run, daemon=True).start()

  def _run(self):
    log_info(f"Started — task: {self.task}", agent_id=self.id)
    self.state["status"] = "running"
    self._sync_live_state()

    self.loop.messages.append(
      HumanMessage(
        content=(
          f"Your assigned task:\n{self.task}\n\n"
          f"You are in a fresh {self.image} container. Begin your work now.\n"
          f"Use `mark_step_completed` after each step and `report_finding` for discoveries."
        )
      )
    )

    nudge: str | None = None
    try:
      for iteration in range(1, self.MAX_ITERATIONS + 1):
        if self.stop_event.is_set() or self.state["status"] == "completed":
          break

        log_info(f"Iteration {iteration}/{self.MAX_ITERATIONS}", agent_id=self.id)
        self.loop.run_turn(nudge=nudge, stop_event=self.stop_event)
        nudge = None

        if self.state["status"] == "completed":
          break

        pending = _drain_queue(self.messages)
        nudge = (
          f"Messages from main agent:\n" + "\n".join(f"- {m}" for m in pending) + "\n\nAcknowledge and continue."
          if pending
          else "Continue your task. If done, use `report_to_main`."
        )
        self.stop_event.wait(0.5)

      if self.state["status"] == "running" and not self.stop_event.is_set():
        self.state["status"] = "stopped"
        self.state["summary"] = self.state["summary"] or "Max iterations reached."
        self._sync_live_state()

    except InterruptedError:
      log_info("Sub-agent interrupted", agent_id=self.id)
    except Exception as e:
      if self.stop_event.is_set():
        log_info(f"Stopped during error: {e}", agent_id=self.id)
      else:
        log_error(f"Error: {e}", agent_id=self.id)
        self.state["status"] = "error"
        self.state["summary"] = f"Error: {e}"
        self._sync_live_state()

  def send_message(self, message: str):
    self.messages.put(message)

  def get_status(self) -> str:
    return self.state["status"]

  def get_completed_steps(self) -> list[str]:
    return self.state["completed_steps"]

  def get_findings(self) -> list[str]:
    return self.state["findings"]

  def get_summary(self) -> str | None:
    return self.state["summary"]

  def stop(self):
    self.stop_event.set()
    if self.state["status"] in ("starting", "running"):
      self.state["status"] = "stopped"
      self.state["summary"] = self.state["summary"] or "Stopped by user."
      self._sync_live_state()
    try:
      self.controller.stop()
    except Exception as e:
      log_warn(f"Controller stop error: {e}", agent_id=self.id)
