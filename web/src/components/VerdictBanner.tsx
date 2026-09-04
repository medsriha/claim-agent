/**
 * The decision, stated first and largest.
 *
 * The verdict and the reasons are shown in the service's own words — `proceed`,
 * `terminal`, `claim_too_old` — reshaped to read, never restated in wording of ours.
 * Reasons keep the order they arrive in: the service decides it, and the first is the one
 * that names the merchant email's subject line.
 */
import { humanise } from "../display";
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
        <h2 className="verdict-badge">{humanise(verdict)}</h2>
        <p className="verdict-case">{caseId}</p>
      </div>

      {reasons.length > 0 && (
        <ol className="reason-list">
          {reasons.map((reason) => (
            <li key={reason} className="reason">
              {humanise(reason)}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
