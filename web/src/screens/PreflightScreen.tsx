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

interface Conversation {

  readonly sequence: number;
  readonly caseId: string;
  readonly messages: TranscriptMessage[];
  readonly working: boolean;
}

async function lookUpPrecedent(result: PreflightResult): Promise<PrecedentLookup> {
  if (result.verdict !== "proceed") {
    return { found: null, failureMessage: null, sought: false };
  }

  const account = result.record.case.description;
  if (account === null) {

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

async function investigate(
  caseId: string,
  setConversation: React.Dispatch<React.SetStateAction<Conversation | null>>,
): Promise<void> {
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

          if (message.event.kind !== "screened") {
            showLatestAction(stepMessage(message.event));
          }
          return;

        case "result":
          add(reportMessages(message.report, message.reportUnavailable), true);
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

          current === null || current.caseId !== caseId
            ? current
            : {
                ...current,
                messages: screened,

                working: true,
              },
        );

        await investigate(caseId, setConversation);
      })
      .catch((error: unknown) => {

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
