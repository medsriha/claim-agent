/**
 * What the screen shows when a claim could not be screened at all.
 *
 * The sentence comes from the service wherever it sent one; only the heading is ours.
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

export function FailureNotice({ kind, message, onRetry }: FailureNoticeProps): React.JSX.Element {
  return (
    <section className="failure" role="alert">
      <h2 className="failure-title">{HEADINGS[kind]}</h2>
      <p className="failure-message">{message}</p>
      <button className="button-secondary" type="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}
