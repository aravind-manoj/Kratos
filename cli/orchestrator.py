import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from cli.core.live_state import LiveState
from cli.core.logger import log_error, log_info, log_warn
from cli.core.main_agent import MainAgent
from cli.core.sub_agent import SubAgent

CONTINUE_NUDGE = (
  "Continue monitoring your sub-agents. Check their status, completed steps, "
  "and findings. Use send_message to assist if needed. When all are done, "
  "collect findings and call finalize_findings."
)

@dataclass
class ScanResult:
  targets: list[str]
  vectors: list[str]
  note: str
  status: str
  started_at: str
  completed_at: str
  summary: str | None = None
  findings: list[dict] = field(default_factory=list)
  subagents: list[dict[str, Any]] = field(default_factory=list)
  stopped_by_user: bool = False

  def to_dict(self) -> dict[str, Any]:
    return {
      "targets": self.targets,
      "vectors": self.vectors,
      "note": self.note,
      "status": self.status,
      "started_at": self.started_at,
      "completed_at": self.completed_at,
      "summary": self.summary,
      "findings": self.findings,
      "subagents": self.subagents,
      "stopped_by_user": self.stopped_by_user,
    }


class PentestOrchestrator:
  def __init__(
    self,
    live_state: LiveState,
    default_image: str = "ubuntu:latest",
    max_iterations: int = 50,
    provider: str | None = None,
  ):
    self.live_state = live_state
    self.default_image = default_image
    self.max_iterations = max_iterations
    self.provider = provider
    self.subagents: dict[str, SubAgent] = {}
    self.stop_event = threading.Event()
    self._original_sigint = None

  def _handle_sigint(self, signum, frame):
    log_warn("Interrupt received — stopping scan...", agent_id="main")
    self.stop_event.set()

  def _cleanup(self):
    log_info("Cleaning up sub-agents...", agent_id="main")
    for sub in self.subagents.values():
      try:
        sub.stop()
      except Exception as e:
        log_warn(f"Error stopping subagent: {e}", agent_id="main")

  def run(self, targets: list[str], vectors: list[str], note: str) -> ScanResult:
    started_at = datetime.now(timezone.utc).isoformat()
    self.live_state.init_scan(targets, vectors, note)
    self._original_sigint = signal.signal(signal.SIGINT, self._handle_sigint)

    main_agent = MainAgent(
      live_state=self.live_state,
      subagents=self.subagents,
      stop_event=self.stop_event,
      default_image=self.default_image,
      provider=self.provider,
    )

    target_str = ", ".join(targets)
    nudge = (
      f"Your target is: {target_str}\n"
      f"Suggested attack vectors: {', '.join(vectors)}\n"
      f"User note/instruction: {note}\n\n"
      f"Begin your pentesting assessment. Create sub-agents for each task, "
      f"monitor their progress, and call finalize_findings when done."
    )
    status = "completed"

    try:
      log_info(f"Starting autonomous pentesting against {target_str}", agent_id="main")

      for iteration in range(1, self.max_iterations + 1):
        if self.stop_event.is_set():
          status = "stopped"
          break

        log_info(f"=== Iteration {iteration} ===", agent_id="main")

        try:
          turn = main_agent.run_turn(nudge=nudge)
          nudge = None

          if turn.stopped or self.stop_event.is_set():
            status = "stopped"
            break

          if main_agent.finalized:
            log_info("Findings finalized. Wrapping up...", agent_id="main")
            break

          nudge = CONTINUE_NUDGE

        except InterruptedError:
          status = "stopped"
          break
        except Exception as e:
          log_error(f"Error during iteration {iteration}: {e}", agent_id="main")
          nudge = f"An error occurred: {e}. Please continue your assessment."

        self.stop_event.wait(1.0)

      if not main_agent.finalized and status == "completed":
        status = "max_iterations"

    finally:
      if self._original_sigint is not None:
        signal.signal(signal.SIGINT, self._original_sigint)
      self._cleanup()
      self.live_state.set_scan_status(status)

    payload = main_agent.finalized_payload or {}
    return ScanResult(
      targets=targets,
      vectors=vectors,
      note=note,
      status=status,
      started_at=started_at,
      completed_at=datetime.now(timezone.utc).isoformat(),
      summary=payload.get("summary"),
      findings=payload.get("findings", []),
      subagents=[
        {
          "id": sid,
          "task": sub.task,
          "status": sub.get_status(),
          "completed_steps": sub.get_completed_steps(),
          "findings": sub.get_findings(),
          "summary": sub.get_summary(),
        }
        for sid, sub in self.subagents.items()
      ],
      stopped_by_user=self.stop_event.is_set(),
    )
