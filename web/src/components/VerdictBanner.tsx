/**
 * The decision, stated first and stated largest.
 *
 * A rep reading this needs one thing before anything else: can this claim be worked on,
 * or is it stopped? Everything below the banner is the working behind that answer.
 *
 * When a claim is stopped, every reason is listed, in the order the service ranked them.
 * That order is not cosmetic — the first reason is the one that heads the merchant's
 * email — so the list is printed exactly as it arrives and is never sorted here.
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
        <span className="verdict-badge">{stopped ? "Stopped" : "Carry on"}</span>
        <h2 className="verdict-title">
          {stopped
            ? "This claim cannot be processed"
            : "Nothing rules this claim out"}
        </h2>
        <p className="verdict-case">{caseId}</p>
      </div>

      <p className="verdict-meaning">
        {stopped
          ? "The claim is closed here. A merchant email explaining why is drafted below and waits for your approval."
          : "The four eligibility checks all passed, so the claim would go on to be investigated."}
      </p>

      {reasons.length > 0 && (
        <ol className="reason-list">
          {reasons.map((reason, index) => (
            <li key={reason} className="reason">
              <span className="reason-text">{reasonLabel(reason)}</span>
              {index === 0 && reasons.length > 1 && (
                <span className="reason-lead">leads the merchant email</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
