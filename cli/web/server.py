import asyncio
import logging
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from cli.core.live_state import LiveState

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("kratos.dashboard")
MAX_PENDING_EVENTS = 200

class ConnectionManager:
  def __init__(self):
    self.active: list[WebSocket] = []
    self._loop: asyncio.AbstractEventLoop | None = None
    self._pending: list[dict[str, Any]] = []
    self._lock = threading.Lock()

  def set_loop(self, loop: asyncio.AbstractEventLoop):
    self._loop = loop
    self._flush_pending()

  def _flush_pending(self):
    if not self._loop or not self._loop.is_running():
      return
    with self._lock:
      pending = self._pending
      self._pending = []
    for event in pending:
      asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)

  async def connect(self, websocket: WebSocket):
    await websocket.accept()
    self.active.append(websocket)

  def disconnect(self, websocket: WebSocket):
    if websocket in self.active:
      self.active.remove(websocket)

  async def broadcast(self, data: dict[str, Any]):
    if not self.active:
      return
    dead: list[WebSocket] = []
    for ws in self.active:
      try:
        await ws.send_json(data)
      except Exception as e:
        log.debug("WebSocket send failed: %s", e)
        dead.append(ws)
    for ws in dead:
      self.disconnect(ws)

  def broadcast_sync(self, data: dict[str, Any]):
    if self._loop and self._loop.is_running():
      asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)
      return
    with self._lock:
      self._pending.append(data)
      if len(self._pending) > MAX_PENDING_EVENTS:
        self._pending = self._pending[-MAX_PENDING_EVENTS // 2 :]
    log.debug("Queued dashboard event (loop not ready): %s", data.get("type"))


def create_app(
  live_state: LiveState,
  manager: ConnectionManager,
  on_ready: Callable[[], None] | None = None,
) -> FastAPI:
  @asynccontextmanager
  async def lifespan(app: FastAPI):
    manager.set_loop(asyncio.get_running_loop())
    if on_ready:
      on_ready()
    yield

  app = FastAPI(title="Kratos Live Dashboard", lifespan=lifespan)

  @app.get("/")
  async def index():
    return FileResponse(
      STATIC_DIR / "index.html",
      headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

  @app.get("/health")
  async def health():
    return {"status": "ok"}

  @app.websocket("/ws")
  async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
      snapshot = live_state.snapshot()
      await websocket.send_json({"type": "snapshot", **snapshot})
      while True:
        await websocket.receive_text()
    except WebSocketDisconnect:
      manager.disconnect(websocket)
    except Exception as e:
      manager.disconnect(websocket)
      log.warning("WebSocket error: %s", e)

  return app


class DashboardServer:
  def __init__(self, live_state: LiveState, host: str = "127.0.0.1", port: int = 8765):
    self.live_state = live_state
    self.host = host
    self.port = port
    self.manager = ConnectionManager()
    self._server: uvicorn.Server | None = None
    self._ready = threading.Event()
    live_state.add_listener(self.manager.broadcast_sync)

  @property
  def url(self) -> str:
    return f"http://{self.host}:{self.port}"

  def start(self, timeout: float = 10.0):
    config = uvicorn.Config(
      create_app(self.live_state, self.manager, on_ready=self._ready.set),
      host=self.host,
      port=self.port,
      log_level="warning",
    )
    self._server = uvicorn.Server(config)
    threading.Thread(target=lambda: asyncio.run(self._server.serve()), daemon=True).start()
    self._wait_until_ready(timeout)
    self.manager._flush_pending()

  def _wait_until_ready(self, timeout: float) -> None:
    health_url = f"{self.url}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
      if self._ready.is_set():
        try:
          with urllib.request.urlopen(health_url, timeout=0.5) as resp:
            if resp.status == 200:
              return
        except (urllib.error.URLError, TimeoutError, OSError):
          pass
      time.sleep(0.05)
    raise TimeoutError(f"Dashboard did not become ready within {timeout:.0f}s")

  def stop(self):
    if self._server:
      self._server.should_exit = True
