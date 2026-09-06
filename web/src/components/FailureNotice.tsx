import type { FailureKind } from "../api/failure";

interface FailureNoticeProps {
  kind: FailureKind;
  message: string;

  onRetry: () => void;
}

const HEADINGS: Record<FailureKind, string> = {
  not_found: "No such claim",
  upstream_unavailable: "ShipBob could not be read",
  invalid_request: "The service would not accept that",
  storage_unavailable: "What the service keeps could not be read",
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
