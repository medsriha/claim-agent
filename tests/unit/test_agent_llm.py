"""Building the model and asking it for a form — and what happens when that goes wrong.

**Nothing here reaches Anthropic and nothing here needs a key.** Every question is
answered by a stand-in chat model in this same process, which hands back whatever
the test queued for it: a filled-in form, or the failure the test wants to see
handled. The two tests that do supply a key supply an obviously fake one and never
ask it anything, because building a model opens no connection.

The form used throughout is a small one of our own rather than one of the real
shapes from `claim_agent.agent.schemas`. What is being tested is the plumbing —
which failures are tried again, which are not, and what a caller is handed — and
that is the same whatever form is being asked for.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelRateLimitError,
    ModelTimeoutError,
    OutputParserException,
)
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from claim_agent.agent.llm import StructuredModel, build_chat_model, build_structured_model
from claim_agent.errors import ConfigurationError, UpstreamError
from claim_agent.settings import Settings


class Verdict(BaseModel):
    """A tiny stand-in for one of the forms the investigation really asks for."""

    damaged: bool


class StubChatModel(BaseChatModel):
    """A chat model that answers from a queue instead of over a network.

    Put one item in `replies` for each call the test expects. An item that is an
    exception is raised instead of returned, which is how a test says "the
    provider failed this time". `asked` records one entry per call, so a test can
    show how many attempts were actually made.

    Only `with_structured_output` is really implemented, because that is the only
    thing the code under test uses. `_generate` is here because the base class
    requires it, and answering with an empty message is enough.
    """

    replies: list[Any] = Field(default_factory=list)
    asked: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        """Names this model in anything the library logs about it."""
        return "stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Answer with an empty message. Nothing under test goes through this path."""
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    def with_structured_output(
        self, schema: dict[str, Any] | type, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        """Hand back something that answers with the next queued reply."""

        async def answer(_prompt: LanguageModelInput) -> dict[str, Any] | BaseModel:
            self.asked.append(getattr(schema, "__name__", str(schema)))
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            queued: dict[str, Any] | BaseModel = reply
            return queued

        return RunnableLambda(answer)


def stub_with(*replies: Any) -> StubChatModel:
    """A stand-in chat model queued to answer with each of `replies` in turn."""
    return StubChatModel(replies=list(replies), asked=[])


def settings_with_a_key(**overrides: Any) -> Settings:
    """Test settings carrying a fake key, so the factory has something to accept.

    The key is never used: building a model opens no connection and makes no
    request, so no test here can leave the process.
    """
    return Settings(environment="test", anthropic_api_key="sk-not-a-real-key", **overrides)


# --- The service boots without credentials (NFR-6) ---------------------------


def test_the_module_can_be_imported_without_a_key() -> None:
    """NFR-6: a missing key is a handled state, so nothing about it happens at import time."""
    # Importing this test file already imported the module under test. Building
    # settings with no key at all must also be uneventful, because the service
    # has to start and answer its other routes with no credentials.
    settings = Settings(environment="test", anthropic_api_key=None)

    assert settings.anthropic_api_key is None
    assert build_chat_model is not None


def test_asking_for_a_model_without_a_key_gives_a_message_a_person_can_act_on() -> None:
    """NFR-6, NFR-4: the factory refuses, in words that say what is missing."""
    settings = Settings(environment="test", anthropic_api_key=None)

    with pytest.raises(ConfigurationError) as raised:
        build_chat_model(settings)

    assert "Anthropic API key" in raised.value.message
    assert "ANTHROPIC_API_KEY" in raised.value.message
    # A handled error, so the API answers with it rather than a stack trace. Reported as
    # our own misconfiguration rather than as an upstream failure, so that nobody goes
    # looking at Anthropic's status page for a key we never set.
    assert raised.value.code == "configuration_error"
    assert raised.value.status_code == 503


def test_building_the_whole_thing_without_a_key_refuses_in_the_same_way() -> None:
    """NFR-6: the convenience that assembles both halves fails no more quietly than the factory."""
    settings = Settings(environment="test", anthropic_api_key=None)

    with pytest.raises(ConfigurationError, match="Anthropic API key"):
        build_structured_model(settings)


# --- The settings are what decide how the model is reached (NFR-6) -----------


def test_the_model_name_and_timeout_come_from_the_settings() -> None:
    """NFR-6: a deployment changes which model is asked, and for how long, without a code change."""
    chat = build_chat_model(settings_with_a_key(model="claude-opus-5", model_timeout_seconds=7.5))

    assert chat.model == "claude-opus-5"  # type: ignore[attr-defined]
    assert chat.default_request_timeout == 7.5  # type: ignore[attr-defined]


def test_the_temperature_is_zero_and_the_provider_does_not_retry_for_us() -> None:
    """NFR-1, FR-1.3: variance is not invited, and retrying happens in one place only."""
    chat = build_chat_model(settings_with_a_key())

    assert chat.temperature == 0.0  # type: ignore[attr-defined]
    # Left to this file's own bounded loop. The provider's retries would multiply
    # with ours and neither the step budget nor the report would know.
    assert chat.max_retries == 0  # type: ignore[attr-defined]


def test_how_many_tries_a_question_gets_comes_from_the_settings() -> None:
    """FR-1.3, NFR-6: the bound on retrying is configuration, not a number written in the code."""
    built = build_structured_model(settings_with_a_key(model_max_attempts=4))

    assert built.max_attempts == 4


async def test_the_settings_bound_is_the_one_actually_applied() -> None:
    """FR-1.3: the number from the settings is what stops the retrying, not a default."""
    settings = settings_with_a_key(model_max_attempts=3)
    stub = stub_with(*[ModelConnectionError("dropped")] * 5)

    with pytest.raises(UpstreamError):
        await StructuredModel(stub, max_attempts=settings.model_max_attempts).ask(
            Verdict, "Was it damaged?"
        )

    assert len(stub.asked) == 3


# --- A good answer (NFR-2) ---------------------------------------------------


async def test_a_good_answer_comes_back_as_the_form_that_was_asked_for() -> None:
    """NFR-2: the model answers in a named shape, never in prose to be interpreted."""
    stub = stub_with(Verdict(damaged=True))

    answer = await StructuredModel(stub, max_attempts=2).ask(Verdict, "Was it damaged?")

    assert isinstance(answer, Verdict)
    assert answer.damaged is True
    assert stub.asked == ["Verdict"]


# --- Retrying is bounded, and only for what could succeed (FR-1.3, NFR-6) ----


async def test_a_failure_that_might_pass_next_time_is_tried_again() -> None:
    """NFR-6: a dropped connection is not turned into a failed claim."""
    stub = stub_with(ModelConnectionError("dropped"), Verdict(damaged=False))

    answer = await StructuredModel(stub, max_attempts=2).ask(Verdict, "Was it damaged?")

    assert answer.damaged is False
    assert len(stub.asked) == 2


@pytest.mark.parametrize(
    "failure",
    [
        ModelConnectionError("dropped"),
        ModelTimeoutError("too slow"),
        ModelRateLimitError("slow down"),
    ],
    ids=["connection", "timeout", "rate limit"],
)
async def test_retrying_stops_at_the_allowed_number_of_tries(failure: Exception) -> None:
    """FR-1.3: retries are bounded, so a failing provider cannot keep a run going forever."""
    stub = stub_with(failure, failure, failure, failure)

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=2).ask(Verdict, "Was it damaged?")

    # Two tries, not four, even though four failures were queued.
    assert len(stub.asked) == 2
    assert raised.value.code == "upstream_unavailable"
    assert "could not be reached" in raised.value.message


async def test_a_single_try_means_a_single_try() -> None:
    """FR-1.3: the count includes the first attempt, so one means no retrying at all."""
    stub = stub_with(ModelTimeoutError("too slow"), Verdict(damaged=True))

    with pytest.raises(UpstreamError):
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert len(stub.asked) == 1


@pytest.mark.parametrize(
    "failure",
    [
        ModelAuthenticationError("the key is wrong"),
        ContextOverflowError("the prompt is too long"),
    ],
    ids=["wrong key", "prompt too long"],
)
async def test_a_settled_refusal_is_not_tried_again(failure: Exception) -> None:
    """NFR-6, NFR-4: only what could plausibly succeed next time is retried."""
    stub = stub_with(failure, Verdict(damaged=True))

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=3).ask(Verdict, "Was it damaged?")

    # Asked once. A wrong key and an over-long prompt do not mend themselves, and
    # the queued good answer was never reached.
    assert len(stub.asked) == 1
    assert raised.value.message == "The model provider refused the request."


# --- An answer that will not fit the form (NFR-2, NFR-4) ---------------------


async def test_an_answer_that_will_not_fit_the_form_is_not_asked_for_again() -> None:
    """NFR-2: the identical question would produce the identical unusable shape."""
    stub = stub_with(OutputParserException("not the shape we asked for"), Verdict(damaged=True))

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=3).ask(Verdict, "Was it damaged?")

    assert len(stub.asked) == 1
    assert (
        raised.value.message == "The model's answer did not fit the form it was asked to fill in."
    )


async def test_an_answer_that_is_not_a_form_at_all_is_refused_rather_than_patched_up() -> None:
    """NFR-2, NFR-4: an investigation never runs on fields we filled in ourselves."""
    # The library's own type allows a plain dictionary here, which is what comes
    # back when it could not build the form.
    stub = stub_with({"damaged": True})

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert (
        raised.value.message == "The model's answer did not fit the form it was asked to fill in."
    )


async def test_a_failure_never_comes_back_as_a_half_filled_answer() -> None:
    """NFR-4: every failure ends in front of a person, never in a guess or a None."""
    stub = stub_with(ModelConnectionError("dropped"))

    with pytest.raises(UpstreamError):
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    # Nothing was returned at all — the only two outcomes are the form or a raise.
    assert stub.replies == []


async def test_the_form_that_was_asked_for_is_named_in_the_failure_details() -> None:
    """NFR-3: an engineer can tell which question failed, without the message leaking internals."""
    stub = stub_with(ModelAuthenticationError("the key is wrong"))

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert raised.value.details == {"form": "Verdict"}
    # The provider's own wording never travels out through the API.
    assert "the key is wrong" not in raised.value.message
