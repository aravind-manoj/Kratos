from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from cli.core.logger import log_info

class ContextManager:
  MAX_MESSAGES = 30
  KEEP_TOOL_CALLS_PER_TYPE = 3

  def trim_context(self, messages: list) -> list:
    if len(messages) <= self.MAX_MESSAGES:
      return messages

    kept_ids = self._select_tool_call_ids_to_keep(messages)
    trimmed = self._rebuild_messages(messages, kept_ids)
    self._trim_to_max_messages(trimmed)

    log_info(f"Context trimmed: {len(messages)} → {len(trimmed)} messages")
    return trimmed

  def _select_tool_call_ids_to_keep(self, messages: list) -> set[str]:
    """Keep the most recent complete tool call/result pairs per tool name."""
    tool_call_ids: set[str] = set()
    for msg in messages:
      if isinstance(msg, AIMessage) and msg.tool_calls:
        tool_call_ids.update(tc["id"] for tc in msg.tool_calls)

    tool_counts: dict[str, int] = {}
    kept: set[str] = set()
    for msg in reversed(messages):
      if not isinstance(msg, ToolMessage):
        continue
      if msg.tool_call_id not in tool_call_ids:
        continue

      name = msg.name or "unknown"
      count = tool_counts.get(name, 0)
      if count < self.KEEP_TOOL_CALLS_PER_TYPE:
        kept.add(msg.tool_call_id)
        tool_counts[name] = count + 1

    return kept

  def _rebuild_messages(self, messages: list, kept_ids: set[str]) -> list:
    trimmed: list = []
    for msg in messages:
      if isinstance(msg, SystemMessage | HumanMessage):
        trimmed.append(msg)
        continue

      if isinstance(msg, ToolMessage):
        if msg.tool_call_id in kept_ids:
          trimmed.append(msg)
        continue

      if isinstance(msg, AIMessage):
        if not msg.tool_calls:
          trimmed.append(msg)
          continue

        kept_calls = [tc for tc in msg.tool_calls if tc["id"] in kept_ids]
        if len(kept_calls) == len(msg.tool_calls):
          trimmed.append(msg)
        elif kept_calls:
          trimmed.append(
            AIMessage(
              content=msg.content or "",
              tool_calls=kept_calls,
              id=msg.id,
            )
          )
        elif msg.content:
          trimmed.append(AIMessage(content=msg.content, id=msg.id))

    return trimmed

  def _trim_to_max_messages(self, messages: list) -> None:
    """Drop oldest messages in place until within limit; never split a tool pair."""
    i = 0
    while len(messages) > self.MAX_MESSAGES:
      if i >= len(messages):
        break
      msg = messages[i]
      if isinstance(msg, SystemMessage):
        i += 1
        continue
      if isinstance(msg, HumanMessage | AIMessage) and not (
        isinstance(msg, AIMessage) and msg.tool_calls
      ):
        messages.pop(i)
        continue
      if isinstance(msg, AIMessage) and self._remove_oldest_tool_pair(messages, i):
        continue
      i += 1

  def _remove_oldest_tool_pair(self, messages: list, start: int) -> bool:
    ai_msg = messages[start]
    if not isinstance(ai_msg, AIMessage) or not ai_msg.tool_calls:
      return False

    end = start + 1
    while end < len(messages) and isinstance(messages[end], ToolMessage):
      end += 1

    oldest_call = ai_msg.tool_calls[0]
    call_id = oldest_call["id"]
    remaining_calls = ai_msg.tool_calls[1:]

    if remaining_calls:
      messages[start] = AIMessage(
        content=ai_msg.content or "",
        tool_calls=remaining_calls,
        id=ai_msg.id,
      )
    elif ai_msg.content:
      messages[start] = AIMessage(content=ai_msg.content, id=ai_msg.id)
    else:
      del messages[start:end]
      return True

    for j in range(start + 1, end):
      tool_msg = messages[j]
      if isinstance(tool_msg, ToolMessage) and tool_msg.tool_call_id == call_id:
        del messages[j]
        return True

    del messages[start:end]
    return True
