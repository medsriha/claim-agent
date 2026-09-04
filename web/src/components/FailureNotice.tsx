/**
 * What the screen shows when a claim could not be screened at all.
 *
 * Each kind of failure needs something different from the person reading it, so each gets
 * its own heading and its own suggestion: a case that does not exist is a typo to fix,
 * ShipBob being unreachable is a wait-and-try-again, and the service not answering at all
 * almost always means it is not running.
 *
 * The sentence explaining what happened comes from the service where it supplied one,
 * because it says it more precisely than this screen could guess. What to do about it is
 * the screen's own, because that depends on where you are sitting.
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
  not_found: "Check the case id and try again. Nothing about the claim is wrong — we simply have no claim with that id.",
  upstream_unavailable:
    "Nothing is wrong with the claim itself. The records it needs could not be read, so no verdict was reached. Trying again in a moment is the right move.",
  unreachable:
    "In this demo that usually means the service is not running. Start it with `make run`, and the ShipBob stand-in with `make mock`.",
  unexpected: "Trying again is worth a go. If it keeps happening, this one needs an engineer.",
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
