/**
 * What the screen shows when a claim could not be screened at all.
 *
 * Each kind needs something different from the reader, so each gets its own heading and
 * one line on what to do. The sentence explaining what happened comes from the service
 * where it sent one.
 */
import type { FailureKind } from "../api/client";

interface FailureNoticeProps {
  kind: FailureKind;
  message: string;
  /** Run the same screening again. */
  onRetry: () => void;
}

const HEADINGS: Record<FailureKind, string> = {
  not_found: "No such claim",
  upstream_unavailable: "ShipBob could not be read",
  unreachable: "The claims service is not answering",
  unexpected: "Something went wrong",
};

const SUGGESTIONS: Record<FailureKind, string> = {
  not_found: "Check the case id.",
  upstream_unavailable: "Nothing is wrong with the claim. Try again in a moment.",
  unreachable: "Start it with make run, and the ShipBob stand-in with make mock.",
  unexpected: "Worth trying again.",
};

export function FailureNotice({ kind, message, onRetry }: FailureNoticeProps): React.JSX.Element {
  return (
    <section className="failure" role="alert">
      <h2 className="failure-title">{HEADINGS[kind]}</h2>
      <p className="failure-message">{message}</p>
      <p className="failure-suggestion">{SUGGESTIONS[kind]}</p>
      <button className="button-secondary" type="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}
