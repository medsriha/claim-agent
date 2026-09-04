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
 */
import { useCallback, useState } from "react";

import { ApiFailure } from "../api/failure";
import { screenCase } from "../api/client";
import { CasePicker } from "../components/CasePicker";
import { Thread } from "../chat/Thread";
import { failureTranscript, pickedMessage, transcriptFor } from "../chat/transcript";
import type { TranscriptMessage } from "../chat/transcript";

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
      .then((result) => {
        setConversation((current) =>
          // A conversation that has moved on is left alone: an answer for a claim nobody is
          // looking at any more must not overwrite the one they are.
          current === null || current.caseId !== caseId
            ? current
            : { ...current, messages: transcriptFor(caseId, result), working: false },
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
