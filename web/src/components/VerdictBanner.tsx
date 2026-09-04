/**
 * The decision, stated first and largest.
 *
 * Reasons are printed in the order they arrive and never sorted here: the service ranks
 * them, and the first is the one that heads the merchant's email.
 */
import { reasonLabel } from "../display";
import type { TerminalReason, Verdict } from "../api/types";

interface VerdictBannerProps {
  caseId: string;
  verdict: Verdict;
  reasons: TerminalReason[];
}

export function VerdictBanner({ caseId, verdict, reasons }: VerdictBannerProps): React.JSX.Element {
  const stopped = verdict === "terminal";

  return (
    <section className={stopped ? "verdict verdict-stopped" : "verdict verdict-proceed"}>
      <div className="verdict-head">
        <span className="verdict-badge">{stopped ? "Stopped" : "Proceed"}</span>
        <h2 className="verdict-title">
          {stopped ? "This claim cannot be processed" : "Goes on to investigation"}
        </h2>
        <p className="verdict-case">{caseId}</p>
      </div>

      {reasons.length > 0 && (
        <ol className="reason-list">
          {reasons.map((reason) => (
            <li key={reason} className="reason">
              {reasonLabel(reason)}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
