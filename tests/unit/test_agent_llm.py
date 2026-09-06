from __future__ import annotations

from typing import Any, cast

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
from pydantic import BaseModel, Field, ValidationError

from claim_agent.agent.llm import StructuredModel, build_chat_model, build_structured_model
from claim_agent.errors import ConfigurationError, ModelAnswerDidNotFitError, UpstreamError
from claim_agent.settings import Settings


class Verdict(BaseModel):
    damaged: bool


class StubChatModel(BaseChatModel):
    replies: list[Any] = Field(default_factory=list)
    asked: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    def with_structured_output(
        self, schema: dict[str, Any] | type, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        async def answer(_prompt: LanguageModelInput) -> dict[str, Any] | BaseModel:
            self.asked.append(getattr(schema, "__name__", str(schema)))
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            queued: dict[str, Any] | BaseModel = reply
            return queued

        return RunnableLambda(answer)


def stub_with(*replies: Any) -> StubChatModel:
    return StubChatModel(replies=list(replies), asked=[])


def settings_with_a_key(**overrides: Any) -> Settings:
    return Settings(environment="test", anthropic_api_key="sk-not-a-real-key", **overrides)


def test_the_module_can_be_imported_without_a_key() -> None:
    settings = Settings(environment="test", anthropic_api_key=None)

    assert settings.anthropic_api_key is None
    assert build_chat_model is not None


def test_asking_for_a_model_without_a_key_gives_a_message_a_person_can_act_on() -> None:
    settings = Settings(environment="test", anthropic_api_key=None)

    with pytest.raises(ConfigurationError) as raised:
        build_chat_model(settings)

    assert "Anthropic API key" in raised.value.message
    assert "ANTHROPIC_API_KEY" in raised.value.message

    assert raised.value.code == "configuration_error"
    assert raised.value.status_code == 503


def test_building_the_whole_thing_without_a_key_refuses_in_the_same_way() -> None:
    settings = Settings(environment="test", anthropic_api_key=None)

    with pytest.raises(ConfigurationError, match="Anthropic API key"):
        build_structured_model(settings)


def test_the_model_name_and_timeout_come_from_the_settings() -> None:
    chat = cast(
        Any,
        build_chat_model(settings_with_a_key(model="claude-opus-5", model_timeout_seconds=7.5)),
    )

    assert chat.model == "claude-opus-5"
    assert chat.default_request_timeout == 7.5


def test_no_sampling_setting_is_sent_because_the_model_refuses_them() -> None:
    chat = cast(Any, build_chat_model(settings_with_a_key()))

    assert chat.temperature is None
    assert chat.top_p is None
    assert chat.top_k is None


def test_the_provider_does_not_retry_for_us() -> None:
    chat = cast(Any, build_chat_model(settings_with_a_key()))

    assert chat.max_retries == 0


def test_how_many_tries_a_question_gets_comes_from_the_settings() -> None:
    built = build_structured_model(settings_with_a_key(model_max_attempts=4))

    assert built.max_attempts == 4


async def test_the_settings_bound_is_the_one_actually_applied() -> None:
    settings = settings_with_a_key(model_max_attempts=3)
    stub = stub_with(*[ModelConnectionError("dropped")] * 5)

    with pytest.raises(UpstreamError):
        await StructuredModel(stub, max_attempts=settings.model_max_attempts).ask(
            Verdict, "Was it damaged?"
        )

    assert len(stub.asked) == 3


async def test_a_good_answer_comes_back_as_the_form_that_was_asked_for() -> None:
    stub = stub_with(Verdict(damaged=True))

    answer = await StructuredModel(stub, max_attempts=2).ask(Verdict, "Was it damaged?")

    assert isinstance(answer, Verdict)
    assert answer.damaged is True
    assert stub.asked == ["Verdict"]


async def test_a_failure_that_might_pass_next_time_is_tried_again() -> None:
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
    stub = stub_with(failure, failure, failure, failure)

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=2).ask(Verdict, "Was it damaged?")

    assert len(stub.asked) == 2
    assert raised.value.code == "upstream_unavailable"
    assert "could not be reached" in raised.value.message


async def test_a_single_try_means_a_single_try() -> None:
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
    stub = stub_with(failure, Verdict(damaged=True))

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=3).ask(Verdict, "Was it damaged?")

    assert len(stub.asked) == 1
    assert raised.value.message == "The model provider refused the request."


async def test_an_answer_that_will_not_fit_the_form_is_not_asked_for_again() -> None:
    stub = stub_with(OutputParserException("not the shape we asked for"), Verdict(damaged=True))

    with pytest.raises(ModelAnswerDidNotFitError) as raised:
        await StructuredModel(stub, max_attempts=3).ask(Verdict, "Was it damaged?")

    assert len(stub.asked) == 1
    assert (
        raised.value.message == "The model's answer did not fit the form it was asked to fill in."
    )
    assert raised.value.problems == ("The answer could not be read as the form at all.",)


async def test_the_problems_with_an_answer_are_named_field_by_field() -> None:
    try:
        Verdict.model_validate({"damaged": "maybe"})
    except ValidationError as failure:
        stub = stub_with(failure)

    with pytest.raises(ModelAnswerDidNotFitError) as raised:
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert len(raised.value.problems) == 1
    assert raised.value.problems[0].startswith("damaged: ")


async def test_an_answer_that_is_not_a_form_at_all_is_refused_rather_than_patched_up() -> None:
    stub = stub_with({"damaged": True})

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert (
        raised.value.message == "The model's answer did not fit the form it was asked to fill in."
    )


async def test_a_failure_never_comes_back_as_a_half_filled_answer() -> None:
    stub = stub_with(ModelConnectionError("dropped"))

    with pytest.raises(UpstreamError):
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert stub.replies == []


async def test_the_form_that_was_asked_for_is_named_in_the_failure_details() -> None:
    stub = stub_with(ModelAuthenticationError("the key is wrong"))

    with pytest.raises(UpstreamError) as raised:
        await StructuredModel(stub, max_attempts=1).ask(Verdict, "Was it damaged?")

    assert raised.value.details == {"form": "Verdict"}

    assert "the key is wrong" not in raised.value.message


def test_a_key_set_to_nothing_counts_as_no_key_at_all() -> None:
    for nothing in ("", "   "):
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            build_chat_model(Settings(environment="test", anthropic_api_key=nothing))
