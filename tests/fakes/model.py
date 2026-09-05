from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, convert_to_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ScriptRanOutError(AssertionError):
    pass


class WrongScriptedReplyError(AssertionError):
    pass


@dataclass(frozen=True)
class Ask:
    messages: tuple[BaseMessage, ...]

    schema_name: str | None = None

    tool_names: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(_text_of(message) for message in self.messages)


class ScriptedModel(BaseChatModel):
    replies: list[Any] = Field(default_factory=list)

    asked: list[Ask] = Field(default_factory=list)

    bound_tools: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        self.bound_tools.extend(_tool_name(tool) for tool in tools)
        bound = self.bind(tools=list(tools), tool_choice=tool_choice, **kwargs)
        return cast("Runnable[LanguageModelInput, AIMessage]", bound)

    def with_structured_output(
        self, schema: dict[str, Any] | type, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        if include_raw:
            raise NotImplementedError(
                "The scripted model does not support include_raw, because nothing in this "
                "project asks for it."
            )

        name = getattr(schema, "__name__", str(schema))

        async def answer(prompt: LanguageModelInput) -> dict[str, Any] | BaseModel:
            self.asked.append(Ask(messages=_as_messages(prompt), schema_name=name))
            reply = self._take(wanted=f"an answer shaped like {name}")
            if isinstance(reply, BaseModel | dict):
                return reply
            raise WrongScriptedReplyError(
                f"The scripted model was asked for an answer shaped like {name}, and the next "
                f"queued reply is a {type(reply).__name__}. Queue a filled-in form, or a plain "
                "dictionary when the test is about an answer that does not fit one."
            )

        return RunnableLambda(answer)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.asked.append(Ask(messages=tuple(messages), tool_names=_tools_on_this_call(kwargs)))
        reply = self._take(wanted="a chat reply")
        return ChatResult(generations=[ChatGeneration(message=_as_ai_message(reply))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, **kwargs)

    def _take(self, *, wanted: str) -> Any:
        if not self.replies:
            raise ScriptRanOutError(
                f"The scripted model was asked for {wanted}, and its script is empty. It had "
                f"already answered {len(self.asked) - 1} question(s). Queue one reply for every "
                "call the code under test makes."
            )

        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def scripted(*replies: Any) -> ScriptedModel:
    return ScriptedModel(replies=list(replies))


def _as_ai_message(reply: Any) -> AIMessage:
    if isinstance(reply, AIMessage):
        return reply
    if isinstance(reply, str):
        return AIMessage(content=reply)
    raise WrongScriptedReplyError(
        f"The scripted model was asked for a chat reply, and the next queued reply is a "
        f"{type(reply).__name__}. Queue a message, or a plain string for one with no tool calls."
    )


def _as_messages(prompt: LanguageModelInput) -> tuple[BaseMessage, ...]:
    if isinstance(prompt, str):
        return (HumanMessage(content=prompt),)
    if isinstance(prompt, PromptValue):
        return tuple(prompt.to_messages())
    return tuple(convert_to_messages(prompt))


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content

    said: list[str] = []
    for part in content:
        if isinstance(part, str):
            said.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            said.append(str(part.get("text", "")))
    return "\n".join(said)


def _tools_on_this_call(call_options: dict[str, Any]) -> tuple[str, ...]:
    tools = call_options.get("tools")
    if not isinstance(tools, list):
        return ()
    return tuple(_tool_name(tool) for tool in tools)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, BaseTool):
        return tool.name
    if isinstance(tool, dict):
        described = tool.get("function")
        if isinstance(described, dict) and "name" in described:
            return str(described["name"])
        return str(tool.get("name", tool))
    return str(getattr(tool, "__name__", tool))
