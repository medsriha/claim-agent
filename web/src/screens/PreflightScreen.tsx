/**
 * The one screen: pick a claim, watch the screening and investigation, then review the report.
 *
 * **Two halves, and they work differently.** The quick checks are a replay: the whole
 * answer is fetched first, and only then are the findings played out one at a time, because
 * starting earlier could put "read the parcel ✓" on screen for a read that had not finished
 * or had just failed. The investigation is not a replay — each progress event arrives live. One
 * compact bar previews the latest event and keeps the complete stream in its expandable log.
 *
 * What that leaves invented is worth being exact about, because it used to be everything.
 * The steps are real, their order is real, and their wording is the service's. What is
 * still the screen's own is the moment each one is *drawn*: a message waits its turn behind
 * the ones before it and spins for a beat as it arrives, so a step can appear a little after
 * it happened. The rhythm is a reading aid; the work behind it is not.
 *
 * One claim at a time. Picking a claim replaces the conversation rather than adding to it,
 * so a finding can never be read against the wrong claim. Nothing is kept between visits.
 *
 * **A claim that passes is asked about three times.** The screening comes back first. Then,
 * only if it says the claim may proceed, the screen asks which past claims resemble it — a
 * stopped claim is not asked, because nothing is going to be investigated and it would sit
 * in front of the email a representative has to act on. Then the investigation is asked for,
 * and that one streams.
 *
 * The investigation screens the claim again for itself, so those three cheap reads happen
 * twice. That is knowingly wasteful and costs no AI; the alternative was for the screen to
 * wait for the stream before it could show any of the four checks, which would have made
 * the first thing a representative sees arrive later rather than sooner.
 */
import { useCallback, useState } from "react";

import { ApiFailure } from "../api/failure";
import { findSimilarClaims, screenCase } from "../api/client";
import { investigateCase } from "../api/investigationStream";
import { CasePicker } from "../components/CasePicker";
import { Thread } from "../chat/Thread";
import {
  failureTranscript,
  pickedMessage,
  reportMessages,
  stepMessage,
  transcriptFor,
} from "../chat/transcript";
import type { PrecedentLookup, TranscriptMessage } from "../chat/transcript";
import type { PreflightResult } from "../api/types";

/** One claim's conversation, and whether it is still being screened. */
interface Conversation {
  /**
   * Counts up with every claim picked. Used to draw the conversation afresh, which is what
   * resets the pacing — including when the same claim is picked twice in a row.
   */
  readonly sequence: number;
  readonly caseId: string;
  readonly messages: TranscriptMessage[];
  readonly working: boolean;
}

/**
 * Ask which past claims resemble this one — but only if this one may proceed.
 *
 * The verdict is the service's, read and not second-guessed. A stopped claim is never asked
 * about, and that is reported as not having been asked rather than as having found nothing.
 *
 * **A failure here never fails the screening.** The screening succeeded and a representative
 * can use it; throwing all of it away because a second question went unanswered would lose
 * work that was already done. So a failure becomes a sentence inside the similar-claims
 * message and everything else stands (NFR-4).
 *
 * @param result - The finished screening, read for its verdict and the merchant's words.
 * @returns What was found, or why nothing could be. Never rejects.
 */
async function lookUpPrecedent(result: PreflightResult): Promise<PrecedentLookup> {
  if (result.verdict !== "proceed") {
    return { found: null, failureMessage: null, sought: false };
  }

  // The merchant's own account of what happened is the whole question. It is the only thing
  // the screen has to compare on: the claim has not been split into products yet, so there
  // is no product or price, and guessing at one would be the screen deciding something.
  const account = result.record.case.description;
  if (account === null) {
    // Nothing to search on, and nothing to say about it either. A claim with no description
    // is stopped by the checks anyway, so this is close to unreachable — but a search on an
    // empty string would quietly return whatever the store happened to hold.
    return { found: null, failureMessage: null, sought: false };
  }

  try {
    return { found: await findSimilarClaims(account), failureMessage: null, sought: true };
  } catch (error: unknown) {
    const failure =
      error instanceof ApiFailure
        ? error
        : new ApiFailure("unexpected", "This screen ran into a problem of its own.");
    return { found: null, failureMessage: failure.message, sought: true };
  }
}

/**
 * Ask for the claim to be investigated, and show what the service says as it says it.
 *
 * This is the one place where a message changes in place. Only the newest progress action is
 * retained in the existing activity panel, so live narration never pushes the report away.
 *
 * **A failure never throws away what already arrived.** The screening is on screen and a
 * representative can use it, so a stream that breaks part-way adds what went wrong and
 * leaves everything else standing (NFR-4). That is also why this never rejects.
 *
 * **A conversation that has moved on is left alone.** Every update checks the claim it is
 * for, so a step belonging to a claim nobody is looking at any more is dropped rather than
 * appearing under the one they are.
 *
 * @param caseId - The claim being investigated.
 * @param setConversation - How the conversation is added to.
 */
async function investigate(
  caseId: string,
  setConversation: React.Dispatch<React.SetStateAction<Conversation | null>>,
): Promise<void> {
  const productNames = new Map<string, string>();

  const add = (messages: TranscriptMessage[], stillWorking: boolean): void => {
    setConversation((current) =>
      current === null || current.caseId !== caseId
        ? current
        : { ...current, messages: [...current.messages, ...messages], working: stillWorking },
    );
  };

  const showLatestAction = (message: TranscriptMessage): void => {
    setConversation((current) => {
      if (current === null || current.caseId !== caseId || message.body.kind !== "step") {
        return current;
      }
      const previous = current.messages.find((one) => one.body.kind === "step");
      const history =
        previous?.body.kind === "step"
          ? [...previous.body.history, ...message.body.history]
          : message.body.history;
      return {
        ...current,
        messages: [
          ...current.messages.filter((one) => one.body.kind !== "step"),
          { ...message, body: { ...message.body, history } },
        ],
        working: true,
      };
    });
  };

  try {
    await investigateCase(caseId, (message) => {
      switch (message.kind) {
        case "progress":
          if (
            message.event.claim_line_id !== null &&
            message.event.detail.product !== undefined
          ) {
            productNames.set(message.event.claim_line_id, message.event.detail.product);
          }
          // Screening was already replayed above. Every later SSE action, including model
          // thinking, tool calls, and image analysis, updates the activity bar and is kept
          // in the log revealed when the representative expands it.
          if (message.event.kind !== "screened") {
            showLatestAction(
              stepMessage(message.event, (id) => productNames.get(id) ?? null),
            );
          }
          return;

        case "result":
          add(reportMessages(message.reports, message.reportsUnavailable), true);
          return;

        case "failed":
          add(failureMessages(message.message), false);
          return;

        case "done":
          setConversation((current) =>
            current === null || current.caseId !== caseId
              ? current
              : { ...current, working: false },
          );
          return;
      }
    });
  } catch (error: unknown) {
    const failure =
      error instanceof ApiFailure
        ? error
        : new ApiFailure("unexpected", "This screen ran into a problem of its own.");
    add(failureMessages(failure.message), false);
  }
}

/**
 * What went wrong with an investigation, as a message to add to a conversation.
 *
 * Kept apart from the failure transcript, which *replaces* a conversation. This one is
 * added to the end of one, because the screening it follows succeeded and is worth keeping.
 */
function failureMessages(message: string): TranscriptMessage[] {
  return [
    {
      id: "investigation-failed",
      speaker: "system",
      label: "The investigation could not be completed",
      body: { kind: "findings", findings: [message] },
    },
  ];
}


export function PreflightScreen(): React.JSX.Element {
  const [conversation, setConversation] = useState<Conversation | null>(null);

  const screen = useCallback((caseId: string): void => {
    // Opens with the representative's own line and nothing else. The findings cannot be
    // laid out until there is an answer to lay out.
    setConversation((previous) => ({
      sequence: (previous?.sequence ?? 0) + 1,
      caseId,
      messages: [pickedMessage(caseId)],
      working: true,
    }));

    screenCase(caseId)
      .then(async (result) => {
        const precedent = await lookUpPrecedent(result);
        const screened = transcriptFor(caseId, result, precedent);
        setConversation((current) =>
          // A conversation that has moved on is left alone: an answer for a claim nobody is
          // looking at any more must not overwrite the one they are.
          current === null || current.caseId !== caseId
            ? current
            : {
                ...current,
                messages: screened,
                // Every path finishes in the same structured report, including claims that the
                // cheap checks stopped before the agent ran.
                working: true,
              },
        );

        await investigate(caseId, setConversation);
      })
      .catch((error: unknown) => {
        // The client promises to throw only its own failure type. Anything else would be a
        // bug in this screen rather than a problem with the claim, and it still has to end
        // in something readable rather than a blank page.
        const failure =
          error instanceof ApiFailure
            ? error
            : new ApiFailure("unexpected", "This screen ran into a problem of its own.");
        setConversation((current) =>
          current === null || current.caseId !== caseId
            ? current
            : {
                ...current,
                messages: failureTranscript(caseId, failure.kind, failure.message),
                working: false,
              },
        );
      });
  }, []);

  const retry = useCallback((): void => {
    if (conversation !== null) {
      screen(conversation.caseId);
    }
  }, [conversation, screen]);

  return (
    <main className="screen screen-chat">
      {conversation === null ? (
        <p className="intro">Pick a claim to screen.</p>
      ) : (
        <Thread
          key={conversation.sequence}
          messages={conversation.messages}
          working={conversation.working}
          caseId={conversation.caseId}
          onRetry={retry}
        />
      )}

      <CasePicker
        onPick={screen}
        busy={conversation?.working ?? false}
        picked={conversation?.caseId ?? null}
      />
    </main>
  );
}
