from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import ModelError, OutputParserException
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from claim_agent.agent.budget import UsageMeter
from claim_agent.errors import ConfigurationError, ModelAnswerDidNotFitError, UpstreamError
from claim_agent.observability import get_logger
from claim_agent.settings import Settings

logger = get_logger(__name__)


Answer = TypeVar("Answer", bound=BaseModel)


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Build the chat model the investigation uses, from the process settings."""

    key = settings.anthropic_api_key
    if key is None or not key.get_secret_value().strip():
        logger.warning("model_key_missing", model=settings.model)
        raise ConfigurationError(
            "The claim investigation needs an Anthropic API key and none is configured. "
            "Set ANTHROPIC_API_KEY and try again.",
            details={"model": settings.model},
        )

    return ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
    )


class StructuredModel:
    """The model, asked only for answers that fit a named form (NFR-2)."""

    def __init__(self, chat: BaseChatModel, *, max_attempts: int = 2) -> None:
        """Wrap a chat model that is already built, and say how many tries a question gets."""
        self._chat = chat
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """How many tries one question gets, the first attempt included."""
        return self._max_attempts

    async def ask(
        self,
        schema: type[Answer],
        prompt: LanguageModelInput,
        *,
        on_usage: Callable[[Mapping[str, Any] | None], None] | None = None,
    ) -> Answer:
        """Ask the model one question and get back the form it was asked to fill in."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception_type(UpstreamError),
            reraise=True,
        )

        try:
            answer: BaseModel | dict[str, Any] = await retrying(
                self._attempt, schema, prompt, on_usage
            )
        except (OutputParserException, ValidationError) as exc:
            problems = _problems_in(exc)
            logger.warning("model_answer_unusable", form=schema.__name__, problems=problems)
            raise ModelAnswerDidNotFitError(
                "The model's answer did not fit the form it was asked to fill in.",
                problems=problems,
                details={"form": schema.__name__},
            ) from exc
        except ModelError as exc:
            logger.warning(
                "model_request_refused", form=schema.__name__, failure=type(exc).__name__
            )
            raise UpstreamError(
                "The model provider refused the request.",
                details={"form": schema.__name__},
            ) from exc

        if not isinstance(answer, schema):
            logger.warning("model_answer_not_a_form", form=schema.__name__)
            raise ModelAnswerDidNotFitError(
                "The model's answer did not fit the form it was asked to fill in.",
                problems=(f"The answer was not in the shape of {schema.__name__} at all.",),
                details={"form": schema.__name__},
            )

        return answer

    async def _attempt(
        self,
        schema: type[Answer],
        prompt: LanguageModelInput,
        on_usage: Callable[[Mapping[str, Any] | None], None] | None,
    ) -> BaseModel | dict[str, Any]:
        """Ask once, failing only in the ways that are worth asking again."""
        config = RunnableConfig(callbacks=[UsageMeter(on_usage)]) if on_usage is not None else None
        try:
            structured = self._chat.with_structured_output(schema)
            return await structured.ainvoke(prompt, config=config)
        except TimeoutError as exc:
            logger.warning("model_call_timed_out", form=schema.__name__)
            raise UpstreamError(
                "The model provider did not answer in time.",
                details={"form": schema.__name__},
            ) from exc
        except ModelError as exc:
            if not exc.is_retryable:
                raise
            logger.warning(
                "model_call_failed",
                form=schema.__name__,
                failure=type(exc).__name__,
            )
            raise UpstreamError(
                "The model provider could not be reached.",
                details={"form": schema.__name__},
            ) from exc


def _problems_in(exc: Exception) -> tuple[str, ...]:
    """Say, one sentence per field, what was wrong with an answer that did not fit."""
    cause: BaseException | None = exc
    while cause is not None and not isinstance(cause, ValidationError):
        cause = cause.__cause__
    if not isinstance(cause, ValidationError):
        return ("The answer could not be read as the form at all.",)
    return tuple(
        f"{'.'.join(str(part) for part in problem['loc']) or 'the answer'}: {problem['msg']}"
        for problem in cause.errors()
    )


def build_structured_model(settings: Settings) -> StructuredModel:
    """Build the model the investigation asks, ready to be asked for a form."""
    return StructuredModel(
        build_chat_model(settings),
        max_attempts=settings.model_max_attempts,
    )
