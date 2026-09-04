"""Building the model the investigation asks, and asking it for a filled-in form.

Two jobs live here, and nothing else does.

The first is the one place a chat model is built. Everything about how the model
is reached — which model, how long to wait, how many tries — comes from the
process settings rather than being written into a call site, so a deployment can
change any of it without a code change (NFR-6).

The second is the only way the rest of the investigation is meant to ask the
model anything: hand in one of the forms from `claim_agent.agent.schemas` and get
back a filled-in instance of it. The model is never asked for prose to be
interpreted, and never gets to answer in a shape nobody planned for (NFR-2).

**A missing key is a state, not a crash.** The service has to boot and answer
with no credentials at all, because the whole system must be demonstrable
without live API access (NFR-6). Nothing here touches the key at import time.
The factory is what refuses, with a sentence a person can act on, and only when
somebody actually tries to use a model there is no key for.

**Every failure ends up in front of a human.** A provider that cannot be
reached, a reply that will not fit the form, a key that is wrong: each becomes a
handled error that the API turns into a response. Nothing here returns a
half-filled answer, a `None` standing in for a problem, or a guess (NFR-4).
"""

from __future__ import annotations

from typing import Any, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import ModelError, OutputParserException
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from claim_agent.errors import ConfigurationError, UpstreamError
from claim_agent.observability import get_logger
from claim_agent.settings import Settings

logger = get_logger(__name__)

# The form being asked for — one of the shapes in `claim_agent.agent.schemas`.
# Naming it is what lets `ask` hand back an instance of the very form the caller
# passed in, instead of something the caller has to check the type of itself.
Answer = TypeVar("Answer", bound=BaseModel)


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Build the chat model the investigation uses, from the process settings.

    Call this once per run and pass the result around. It opens no connection and
    makes no request, so building one is cheap; it is the asking that costs.

    The temperature is fixed at zero and is not configurable. Consistency is the
    problem this system exists to solve — the same claim, investigated twice,
    should reach a representative looking the same both times — so anything that
    introduces run-to-run variance in a report needs a specific reason, and
    nobody has one (NFR-1).

    **Be clear about what that buys, because it is less than it sounds.
    Temperature zero is not determinism.** It asks the model for its most likely
    next word rather than a sampled one; it does not make the model repeatable.
    The same prompt can still come back different — providers change models
    behind a name, and floating-point arithmetic on the provider's hardware is
    not bit-for-bit stable. So this is a reduction in variance, not a removal of
    it. The real guarantees in this system are elsewhere and are not the model's
    to break: money is worked out by arithmetic in `claim_agent.domain`, never
    read out of generated text (FR-1.21), and every answer has to fit a form
    before it is accepted (NFR-2).

    Retrying is switched off on the model itself, because the wrapper in this
    file owns it. The provider's own retry loop would multiply with ours — three
    of theirs inside two of ours is six calls, not two — and neither the step
    budget nor the report would know it happened (FR-1.3).

    Args:
        settings: Process configuration. The API key, the model name, and how
            long one call may take all come from here. Passed in rather than
            looked up, so a test and a second application instance can each use
            their own.

    Returns:
        A chat model ready to be asked, or to have the run's tools bound to it.

    Raises:
        ConfigurationError: no Anthropic API key is configured. This is the handled
            state NFR-6 asks for: the service still starts, every route that
            needs no model still answers, and only a caller that actually needs
            the model is turned away — with a message that says what is missing.

            Deliberately not reported as an upstream failure. Nothing upstream has
            gone wrong — we are misconfigured — and telling somebody the model
            provider is unavailable would send them looking at Anthropic's status
            page instead of at their own environment.
    """
    if settings.anthropic_api_key is None:
        logger.warning("model_key_missing", model=settings.model)
        raise ConfigurationError(
            "The claim investigation needs an Anthropic API key and none is configured. "
            "Set ANTHROPIC_API_KEY and try again.",
            details={"model": settings.model},
        )

    return ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        temperature=0.0,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
    )


class StructuredModel:
    """The model, asked only for answers that fit a named form (NFR-2).

    Hand it a chat model that is already built and tell it how many tries one
    question gets. It does not build its own model, for the same reason the
    ShipBob reader does not build its own HTTP client: the application decides
    how the model is configured, and a test can hand in one that answers from
    memory instead of over a network.

    `max_attempts` counts the first try, so the default of two means at most one
    retry. It is kept small deliberately: a run has its own step budget on top of
    this, and a slow model burns a representative's time either way (FR-1.3).

    Every call either returns a filled-in form or raises `UpstreamError`. There
    is no third outcome — no partly filled form, and no `None` meaning "something
    went wrong" — because a conclusion resting on an answer we had to guess at
    would be worse than a claim that failed in front of a person (NFR-4).
    """

    def __init__(self, chat: BaseChatModel, *, max_attempts: int = 2) -> None:
        """Wrap a chat model that is already built, and say how many tries a question gets."""
        self._chat = chat
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """How many tries one question gets, the first attempt included.

        Readable rather than private because it is a bound someone may need to
        account for: a report explaining a model failure can say how many times
        it was tried, and a test can show that the number came from the settings
        rather than being written into the code (FR-1.3).
        """
        return self._max_attempts

    async def ask(self, schema: type[Answer], prompt: LanguageModelInput) -> Answer:
        """Ask the model one question and get back the form it was asked to fill in.

        Args:
            schema: The form the answer has to fit — one of the shapes in
                `claim_agent.agent.schemas`. The model is told what the fields
                are and is only allowed to answer in them.
            prompt: What to ask. A string, or the messages of a conversation.

        Returns:
            An instance of `schema`, with every field validated. Nothing else.

        Raises:
            UpstreamError: the provider could not be reached within the allowed
                tries; or it refused the request in a way that another try would
                not fix; or its answer did not fit the form. Each is a handled
                failure that ends in front of a representative (NFR-4).
        """
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception_type(UpstreamError),
            reraise=True,
        )

        try:
            # Annotated because the retry helper cannot know what the function it
            # runs returns; without this, everything downstream would lose its type.
            answer: BaseModel | dict[str, Any] = await retrying(self._attempt, schema, prompt)
        except (OutputParserException, ValidationError) as exc:
            # A reply that will not fit the form is a settled answer, not a
            # stumble, so it is not retried. Asking the identical question in the
            # identical way is the one thing least likely to produce a different
            # shape — especially at temperature zero, where we have deliberately
            # asked for the model's most likely answer rather than a fresh sample.
            # A retry here would spend a representative's time and the step budget
            # to arrive at the same refusal. Getting a usable answer needs a
            # changed question, and changing the question is a decision for
            # whoever writes the prompts, not something to do silently in here.
            logger.warning("model_answer_unusable", form=schema.__name__, reason=str(exc))
            raise UpstreamError(
                "The model's answer did not fit the form it was asked to fill in.",
                details={"form": schema.__name__},
            ) from exc
        except ModelError as exc:
            # Everything the provider reports that another try cannot mend: a key
            # that is wrong, a model name that does not exist, a request we built
            # badly, a prompt too long for the model. The retry loop below lets
            # these straight through, so this is where they are turned into
            # something the API can answer with.
            logger.warning(
                "model_request_refused", form=schema.__name__, failure=type(exc).__name__
            )
            raise UpstreamError(
                "The model provider refused the request.",
                details={"form": schema.__name__},
            ) from exc

        if not isinstance(answer, schema):
            # The library's own type allows a plain dictionary here, which is what
            # comes back when it could not build the form. We refuse it rather
            # than patch it up: an investigation must never run on fields we
            # filled in ourselves (NFR-2, NFR-4).
            logger.warning("model_answer_not_a_form", form=schema.__name__)
            raise UpstreamError(
                "The model's answer did not fit the form it was asked to fill in.",
                details={"form": schema.__name__},
            )

        return answer

    async def _attempt(
        self, schema: type[Answer], prompt: LanguageModelInput
    ) -> BaseModel | dict[str, Any]:
        """Ask once, failing only in the ways that are worth asking again.

        Which failures those are is not our judgement to make: the model library
        marks each provider condition it knows about as retryable or not — a
        dropped connection, a timeout, a rate limit and a fault at the provider's
        end are, a wrong key and a bad request are not — and this reads that mark
        rather than keeping a list of its own. A list here would quietly go stale
        every time the library learned about a new condition.

        Comes back with whatever the library produced, which the caller then
        checks is really the form that was asked for.

        A plain timeout is handled separately from those marks, because NFR-4 names
        a timeout outright and one can reach us without the library having labelled
        it. Anything else unexpected is deliberately left to travel: a mistake in
        our own code should look like a mistake, not like the provider being down.

        Raises:
            UpstreamError: the call failed in a way another try might mend. This
                is the only exception the retry loop above acts on.
        """
        try:
            structured = self._chat.with_structured_output(schema)
            return await structured.ainvoke(prompt)
        except TimeoutError as exc:
            # A timeout is named in NFR-4 as something that has to end with a person,
            # and it does not always arrive dressed as one of the library's own
            # conditions — a provider client, or our own timeout, can raise the plain
            # built-in. Left to travel as it is, it would escape this wrapper entirely
            # and the run above would have to catch anything at all to stay safe.
            logger.warning("model_call_timed_out", form=schema.__name__)
            raise UpstreamError(
                "The model provider did not answer in time.",
                details={"form": schema.__name__},
            ) from exc
        except ModelError as exc:
            if not exc.is_retryable:
                # Handed to the caller untouched, so that the retry loop does not
                # act on it and `ask` can say what actually went wrong.
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


def build_structured_model(settings: Settings) -> StructuredModel:
    """Build the model the investigation asks, ready to be asked for a form.

    This is the one call the rest of the investigation should make. It exists so
    that the number of tries a question gets always comes from the settings: a
    caller assembling the two halves by hand could leave that out and get a
    different bound than the deployment asked for (NFR-6).

    Raises:
        ConfigurationError: no Anthropic API key is configured. See `build_chat_model`.
    """
    return StructuredModel(
        build_chat_model(settings),
        max_attempts=settings.model_max_attempts,
    )
