import re
import socket
import threading
import time
from typing import Callable
import docker
import pyte
from cli.core.logger import log_error, log_info

TTY_COLS = 160
TTY_ROWS = 80
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

class Controller:
  def __init__(
    self,
    image: str = "ubuntu:latest",
    tag: str | None = None,
    on_buffer_update: Callable[[str], None] | None = None,
  ):
    self.client = docker.from_env()
    self.image = image
    self.tag = tag
    self.container = None
    self.sock = None
    self.buffer = ""
    self.lock = threading.Lock()
    self.running = False
    self.on_buffer_update = on_buffer_update
    self._last_pushed_length = 0
    self._last_emitted_parsed: str | None = None
    self._exec_id: str | None = None
    self._pyte_screen = pyte.Screen(TTY_COLS, TTY_ROWS)
    self._pyte_stream = pyte.Stream(self._pyte_screen)

  def start(self):
    log_info(f"Starting container ({self.image})", agent_id=self.tag)

    run_kwargs = {
      "image": self.image,
      "command": "tail -f /dev/null",
      "detach": True,
      "tty": True,
    }
    if self.tag:
      run_kwargs["name"] = self.tag

    self.container = self.client.containers.run(**run_kwargs)
    exec_create = self.client.api.exec_create(
      self.container.id, cmd="/bin/bash", stdin=True, tty=True
    )
    self._exec_id = exec_create["Id"]

    self.sock = self.client.api.exec_start(
      self._exec_id, detach=False, tty=True, socket=True
    )
    self.client.api.exec_resize(self._exec_id, height=TTY_ROWS, width=TTY_COLS)

    self.running = True
    threading.Thread(target=self._read_stream, daemon=True).start()
    threading.Thread(target=self._sync_live, daemon=True).start()

  def _read_stream(self):
    while self.running:
      try:
        data = self.sock._sock.recv(4096)
        if not data:
          break
        with self.lock:
          self.buffer += data.decode("utf-8", errors="ignore")
      except socket.timeout:
        continue
      except Exception as e:
        if self.running:
          log_error(f"Error reading stream: {e}", agent_id=self.tag)
        break

  def _sync_live(self):
    while self.running:
      parsed = ""
      should_push = False
      with self.lock:
        if len(self.buffer) != self._last_pushed_length:
          parsed = self._parse_buffer(self.buffer)
          self._last_pushed_length = len(self.buffer)
          should_push = True

      if (should_push and self.on_buffer_update):
        if parsed != self._last_emitted_parsed:
          self._last_emitted_parsed = parsed
          try:
            self.on_buffer_update(parsed)
          except Exception as e:
            log_error(f"Buffer callback failed: {e}", agent_id=self.tag)

      time.sleep(0.05)

  def _parse_buffer(self, buffer: str) -> str:
    self._pyte_screen.reset()
    self._pyte_stream.feed(buffer)
    lines: list[str] = []
    for row in self._pyte_screen.display:
      line = "".join(row).rstrip()
      if line:
        lines.append(line)
    return _CONTROL_CHARS.sub("", "\n".join(lines))

  def get_screen(self, last_chars: int = 2000) -> str:
    with self.lock:
      output = self._parse_buffer(self.buffer)
      if len(output) <= last_chars:
        return output
      return (
        f"... [Output truncated, showing last {last_chars} characters] ...\n"
        f"{output[-last_chars:]}"
      )

  def send_command(self, cmd: str):
    self.sock._sock.send((cmd + "\n").encode("utf-8"))
    time.sleep(0.5)

  def send_keys(self, keys: str):
    self.sock._sock.send(keys.encode("utf-8"))

  def stop(self):
    self.running = False
    if self.sock:
      self.sock.close()
    if self.container:
      try:
        self.container.stop()
        self.container.remove()
      except Exception as e:
        log_error(f"Container cleanup error: {e}", agent_id=self.tag)
    log_info("Container stopped", agent_id=self.tag)
