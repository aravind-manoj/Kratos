import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from cli.core.live_state import LiveState

STATIC_DIR = Path(__file__).parent / "static"

class ConnectionManager:
  def __init__(self):
    self.active: list[WebSocket] = []
    self._loop: asyncio.AbstractEventLoop | None = None

  def set_loop(self, loop: asyncio.AbstractEventLoop):
    self._loop = loop

  async def connect(self, websocket: WebSocket):
    await websocket.accept()
    self.active.append(websocket)

  def disconnect(self, websocket: WebSocket):
    if websocket in self.active:
      self.active.remove(websocket)

  async def broadcast(self, data: dict[str, Any]):
    dead: list[WebSocket] = []
    for ws in self.active:
      try:
        await ws.send_json(data)
      except Exception:
        dead.append(ws)
    for ws in dead:
      self.disconnect(ws)

  def broadcast_sync(self, data: dict[str, Any]):
    if self._loop and self._loop.is_running():
      asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)


def create_app(live_state: LiveState, manager: ConnectionManager) -> FastAPI:
  @asynccontextmanager
  async def lifespan(app: FastAPI):
    manager.set_loop(asyncio.get_running_loop())
    yield

  app = FastAPI(title="Kratos Live Dashboard", lifespan=lifespan)

  @app.get("/")
  async def index():
    return FileResponse(STATIC_DIR / "index.html")

  @app.websocket("/ws")
  async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
      await websocket.send_json({"type": "snapshot", **live_state.snapshot()})
      while True:
        await websocket.receive_text()
    except WebSocketDisconnect:
      manager.disconnect(websocket)

  return app

class DashboardServer:
  def __init__(self, live_state: LiveState, host: str = "127.0.0.1", port: int = 8765):
    self.live_state = live_state
    self.host = host
    self.port = port
    self.manager = ConnectionManager()
    self._server: uvicorn.Server | None = None
    live_state.add_listener(self.manager.broadcast_sync)

  @property
  def url(self) -> str:
    return f"http://{self.host}:{self.port}"

  def start(self):
    config = uvicorn.Config(
      create_app(self.live_state, self.manager),
      host=self.host,
      port=self.port,
      log_level="warning",
    )
    self._server = uvicorn.Server(config)
    threading.Thread(target=lambda: asyncio.run(self._server.serve()), daemon=True).start()

  def stop(self):
    if self._server:
      self._server.should_exit = True
