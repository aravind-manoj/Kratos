import threading
from dataclasses import dataclass
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from cli.core.context_manager import ContextManager
from cli.core.logger import log_info, log_error

@dataclass
class TurnResult:
  stopped: bool = False

class ReactLoop:
  MAX_TOOL_ROUNDS = 20

  def __init__(self, llm, tools: list, system_prompt: str, agent_id: str = "agent"):
    self.llm = llm.bind_tools(tools)
    self.tools_by_name = {t.name: t for t in tools}
    self.messages = [SystemMessage(content=system_prompt)]
    self.context_manager = ContextManager()
    self.agent_id = agent_id

  def trim_if_needed(self) -> None:
    if len(self.messages) > ContextManager.MAX_MESSAGES:
      self.messages = self.context_manager.trim_context(self.messages)

  def run_turn(
    self,
    nudge: str | None = None,
    stop_event: threading.Event | None = None,
  ) -> TurnResult:
    if nudge:
      self.messages.append(HumanMessage(content=nudge))

    for round_num in range(self.MAX_TOOL_ROUNDS):
      if stop_event and stop_event.is_set():
        return TurnResult(stopped=True)

      log_info(f"LLM inference (round {round_num + 1})", agent_id=self.agent_id)
      response = self.llm.invoke(self.messages)
      self.messages.append(response)

      if not response.tool_calls:
        break

      for tc in response.tool_calls:
        if stop_event and stop_event.is_set():
          return TurnResult(stopped=True)

        name = tc["name"]
        args = tc.get("args") or {}
        tool = self.tools_by_name.get(name)
        log_info(f"Tool: {name}({args})", agent_id=self.agent_id)

        try:
          result = tool.invoke(args) if tool else f"Unknown tool: {name}"
        except InterruptedError:
          raise
        except Exception as e:
          log_error(f"Tool {name} failed: {e}", agent_id=self.agent_id)
          result = f"Tool error: {e}"

        self.messages.append(
          ToolMessage(content=str(result), tool_call_id=tc["id"], name=name)
        )

      self.trim_if_needed()

    self.trim_if_needed()
    return TurnResult()
