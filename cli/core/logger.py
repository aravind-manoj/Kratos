import sys

def _log(message: str, agent_id: str | None = None, *, err: bool = False) -> None:
  prefix = f"[{agent_id}] {message}" if agent_id else message
  print(prefix, file=sys.stderr if err else sys.stdout)


def log_info(message: str, agent_id: str | None = None) -> None:
  _log(message, agent_id)


def log_warn(message: str, agent_id: str | None = None) -> None:
  _log(message, agent_id, err=True)


def log_error(message: str, agent_id: str | None = None) -> None:
  _log(message, agent_id, err=True)
