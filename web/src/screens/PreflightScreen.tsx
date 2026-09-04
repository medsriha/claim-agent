/**
 * The one screen: pick a claim, watch the screening report back, act on the email.
 *
 * The important decision here is that **the pacing is a replay, not a race.** The whole
 * answer is fetched first, and only then are the findings played out one at a time. The
 * tempting alternative — start playing findings while the request is still in flight — can
 * put "read the parcel ✓" on screen for a read that has not finished, or for one that
 * failed a moment later. Waiting first means every finding shown is a finding the service
 * really produced, and a claim that fails shows a failure and no findings at all.
 *
 * One claim at a time. Picking a claim replaces the conversation rather than adding to it,
 * so a finding can never be read against the wrong claim. Nothing is kept between visits.
 *
 * **A claim that passes is asked about twice.** After the screening comes back, and only if
 * it says the claim may proceed, the screen asks which past claims resemble it. A stopped
 * claim is not asked: nothing is going to be investigated, so how comparable claims went
 * helps nobody, and it would sit in front of the email a representative has to act on. Both
 * answers are in hand before the conversation starts playing, which is the same replay rule
 * as before — a second request still in flight would put a finished-looking step on screen
 * for work that had not finished.
 */
import { useCallback, useState } from "react";

import { ApiFailure } from "../api/failure";
import { findSimilarClaims, screenCase } from "../api/client";
import { CasePicker } from "../components/CasePicker";
import { Thread } from "../chat/Thread";
import { failureTranscript, pickedMessage, transcriptFor } from "../chat/transcript";
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
        setConversation((current) =>
          // A conversation that has moved on is left alone: an answer for a claim nobody is
          // looking at any more must not overwrite the one they are.
          current === null || current.caseId !== caseId
            ? current
            : {
                ...current,
                messages: transcriptFor(caseId, result, precedent),
                working: false,
              },
        );
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
