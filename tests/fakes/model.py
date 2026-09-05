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
    """The code asked one more question than the test queued an answer for.

    An `AssertionError` on purpose: this is a test that did not say enough rather
    than a fault in the code being tested, and pytest reports it as the failed
    expectation it is.
    """


class WrongScriptedReplyError(AssertionError):
    """The next queued reply is not the kind of thing this call can hand back.

    Raised when a form was queued and an ordinary chat answer was asked for, or the
    other way round — which almost always means the replies were queued in the
    wrong order. Saying so plainly beats handing back something unusable.
    """


@dataclass(frozen=True)
class Ask:
    """One question the scripted model was asked, written down as it arrived."""

    messages: tuple[BaseMessage, ...]
    """Everything that was sent, in order, the system message included."""

    schema_name: str | None = None
    """The form that was asked for, or `None` for an ordinary chat call."""

    tool_names: tuple[str, ...] = ()
    """The tools the model held for this particular call. Usually empty."""

    @property
    def text(self) -> str:
        """Every word that was said to the model, joined into one string.

        Written for assertions like `"outer_packaging_photo" in ask.text`. Pictures
        and other parts of a message that are not text are left out, because there
        is nothing to match against in them.
        """
        return "\n".join(_text_of(message) for message in self.messages)


class ScriptedModel(BaseChatModel):
    """A chat model that answers from a queue rather than over a network.

    Usable anywhere the real one is: hand it to the investigation's structured
    asker, bind tools to it, or drive a tool-use loop with it. This module's own
    description says what may be queued and what gets written down.
    """

    replies: list[Any] = Field(default_factory=list)
    """The answers still to be given, in the order they will be given.

    Readable and writable, so a test can queue more part-way through, or show at
    the end that everything it queued was actually used.
    """

    asked: list[Ask] = Field(default_factory=list)
    """One entry per question asked so far, oldest first."""

    bound_tools: list[str] = Field(default_factory=list)
    """The name of every tool ever bound to this model, in the order it was bound.

    Kept apart from `asked` because it answers a different question. This says what
    the model was ever offered, which a test can check without the model being
    asked anything (FR-1.2); `Ask.tool_names` says what it held on one call.
    """

    @property
    def _llm_type(self) -> str:
        """Names this model in anything the model library logs about it."""
        return "scripted"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Write down which tools were offered, and hand back a model carrying them."""
        self.bound_tools.extend(_tool_name(tool) for tool in tools)
        bound = self.bind(tools=list(tools), tool_choice=tool_choice, **kwargs)
        # `bind` is typed for messages in general, while the real thing promises the
        # narrower one. Nothing changes shape here; only the annotation does.
        return cast("Runnable[LanguageModelInput, AIMessage]", bound)

    def with_structured_output(
        self, schema: dict[str, Any] | type, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        """Hand back something that answers with the next queued form.

        Args:
            schema: The form being asked for. Only its name is used, and only so
                the record says which question was asked.
            include_raw: Not supported. The real thing wraps the answer up with the
                unparsed reply beside it, nothing in this project asks for that,
                and pretending to support it would hide a mistake rather than
                surface one.
            **kwargs: Accepted and ignored, so a caller passing the real model's
                options still works.

        Raises:
            NotImplementedError: `include_raw` was asked for.
        """
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
        """Answer one ordinary chat call with the next queued message."""
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
        """Answer an awaited call exactly as a plain one, since nothing here waits."""
        return self._generate(messages, stop, **kwargs)

    def _take(self, *, wanted: str) -> Any:
        """Take the next queued reply, raising a queued exception rather than returning it.

        Raises:
            ScriptRanOutError: nothing is left in the script. The message says how many
                questions were answered before this one, which is usually enough to
                see which call the test did not plan for.
        """
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
    """A scripted model queued to answer with each of `replies` in turn."""
    return ScriptedModel(replies=list(replies))


def _as_ai_message(reply: Any) -> AIMessage:
    """Turn a queued chat reply into the message a caller gets back.

    Raises:
        WrongScriptedReplyError: the queued reply is a form, which belongs to a question
            asked through `with_structured_output` rather than to this call.
    """
    if isinstance(reply, AIMessage):
        return reply
    if isinstance(reply, str):
        return AIMessage(content=reply)
    raise WrongScriptedReplyError(
        f"The scripted model was asked for a chat reply, and the next queued reply is a "
        f"{type(reply).__name__}. Queue a message, or a plain string for one with no tool calls."
    )


def _as_messages(prompt: LanguageModelInput) -> tuple[BaseMessage, ...]:
    """Turn anything a caller may pass as a prompt into a plain list of messages.

    A caller may hand over a bare string, a built prompt, or a list of messages.
    Recording all three the same way is what lets a test assert on the wording
    without caring which of them the code under test happened to use.
    """
    if isinstance(prompt, str):
        return (HumanMessage(content=prompt),)
    if isinstance(prompt, PromptValue):
        return tuple(prompt.to_messages())
    return tuple(convert_to_messages(prompt))


def _text_of(message: BaseMessage) -> str:
    """Every word in one message, with pictures and other non-text parts left out."""
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
    """The tools bound for one call, read back off that call's own options."""
    tools = call_options.get("tools")
    if not isinstance(tools, list):
        return ()
    return tuple(_tool_name(tool) for tool in tools)


def _tool_name(tool: Any) -> str:
    """What a tool is called, whichever of the several shapes it arrived in.

    A tool may be one of the model library's own tool objects, a plain function, or
    a dictionary describing one — either flat or wrapped under a `function` key,
    which is the shape a provider's own schema uses. Anything else falls back to how
    it prints, so an unfamiliar shape still shows up in the record instead of
    stopping the test.
    """
    if isinstance(tool, BaseTool):
        return tool.name
    if isinstance(tool, dict):
        described = tool.get("function")
        if isinstance(described, dict) and "name" in described:
            return str(described["name"])
        return str(tool.get("name", tool))
    return str(getattr(tool, "__name__", tool))
