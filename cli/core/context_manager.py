from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from cli.core.logger import log_info


class ContextManager:
  MAX_MESSAGES = 20
  KEEP_TOOL_CALLS_PER_TYPE = 3

  def trim_context(self, messages: list) -> list:
    if len(messages) <= self.MAX_MESSAGES:
      return messages

    tool_counts: dict[str, int] = {}
    tool_call_ids_to_keep: set[str] = set()

    for msg in reversed(messages):
      if isinstance(msg, ToolMessage):
        name = msg.name or "unknown"
        count = tool_counts.get(name, 0)
        if count < self.KEEP_TOOL_CALLS_PER_TYPE:
          tool_call_ids_to_keep.add(msg.tool_call_id)
          tool_counts[name] = count + 1

    trimmed: list = []
    for msg in messages:
      if isinstance(msg, SystemMessage | HumanMessage):
        trimmed.append(msg)
        continue

      if isinstance(msg, ToolMessage):
        if msg.tool_call_id in tool_call_ids_to_keep:
          trimmed.append(msg)
        continue

      if isinstance(msg, AIMessage):
        if msg.tool_calls:
          kept = [tc for tc in msg.tool_calls if tc["id"] in tool_call_ids_to_keep]
          if kept:
            trimmed.append(
              AIMessage(
                content=msg.content or "[Older tool calls removed]",
                tool_calls=kept,
                id=msg.id,
              )
            )
          elif msg.content:
            trimmed.append(AIMessage(content=msg.content, id=msg.id))
        else:
          trimmed.append(msg)

    log_info(f"Context trimmed: {len(messages)} → {len(trimmed)} messages")
    return trimmed
