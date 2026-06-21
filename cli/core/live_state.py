import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("kratos.live_state")

@dataclass
class SubAgentSnapshot:
  id: str
  task: str
  status: str = "starting"
  completed_steps: list[str] = field(default_factory=list)
  findings: list[str] = field(default_factory=list)
  buffer: str = ""
  summary: str | None = None

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class ScanSnapshot:
  targets: list[str]
  status: str = "starting"
  started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  note: str = ""
  vectors: list[str] = field(default_factory=list)

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


class LiveState:
  def __init__(self):
    self._lock = threading.Lock()
    self._scan: ScanSnapshot | None = None
    self._subagents: dict[str, SubAgentSnapshot] = {}
    self._listeners: list[Callable[[dict[str, Any]], None]] = []

  def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
    with self._lock:
      self._listeners.append(listener)

  def _emit(self, event: dict[str, Any]) -> None:
    with self._lock:
      listeners = list(self._listeners)
    for listener in listeners:
      try:
        listener(event)
      except Exception as e:
        log.warning("LiveState listener failed: %s", e)

  def init_scan(self, targets: list[str], vectors: list[str], note: str) -> None:
    with self._lock:
      self._scan = ScanSnapshot(targets=targets, vectors=vectors, note=note, status="running")
      self._subagents = {}
      scan = self._scan.to_dict()
    self._emit({"type": "scan_update", "scan": scan})

  def set_scan_status(self, status: str) -> None:
    with self._lock:
      if self._scan:
        self._scan.status = status
        scan = self._scan.to_dict()
      else:
        scan = None
    if scan:
      self._emit({"type": "scan_update", "scan": scan})

  def register_subagent(self, subagent_id: str, task: str) -> None:
    with self._lock:
      self._subagents[subagent_id] = SubAgentSnapshot(id=subagent_id, task=task)
      sub = self._subagents[subagent_id].to_dict()
    self._emit({"type": "subagent_update", "subagent": sub})

  def update_subagent(
    self,
    subagent_id: str,
    *,
    status: str | None = None,
    completed_steps: list[str] | None = None,
    findings: list[str] | None = None,
    summary: str | None = None,
  ) -> None:
    with self._lock:
      sub = self._subagents.get(subagent_id)
      if not sub:
        return
      if status is not None:
        sub.status = status
      if completed_steps is not None:
        sub.completed_steps = list(completed_steps)
      if findings is not None:
        sub.findings = list(findings)
      if summary is not None:
        sub.summary = summary
      payload = sub.to_dict()
    self._emit({"type": "subagent_update", "subagent": payload})

  def update_buffer(self, subagent_id: str, buffer: str) -> None:
    with self._lock:
      sub = self._subagents.get(subagent_id)
      if not sub:
        return
      if sub.buffer == buffer:
        return
      sub.buffer = buffer
    self._emit({"type": "terminal_update", "subagent_id": subagent_id, "buffer": buffer})

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return {
        "scan": self._scan.to_dict() if self._scan else None,
        "subagents": [s.to_dict() for s in self._subagents.values()],
      }
