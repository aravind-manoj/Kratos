import socket
import threading
import time
from typing import Callable

import docker
import pyte

from cli.core.logger import log_error, log_info


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
    self._pyte_screen = pyte.Screen(200, 50)
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

    self.sock = self.client.api.exec_start(
      exec_create["Id"], detach=False, tty=True, socket=True
    )

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
      needs_update = False
      with self.lock:
        if len(self.buffer) > self._last_pushed_length:
          parsed = self._parse_buffer(self.buffer)
          self._last_pushed_length = len(self.buffer)
          needs_update = True

      if needs_update and self.on_buffer_update:
        try:
          self.on_buffer_update(parsed)
        except Exception as e:
          log_error(f"Buffer callback failed: {e}", agent_id=self.tag)

      time.sleep(0.5)

  def _parse_buffer(self, buffer: str) -> str:
    self._pyte_screen.reset()
    self._pyte_stream.feed(buffer)
    return "\n".join(line.rstrip() for line in self._pyte_screen.display).strip()

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
