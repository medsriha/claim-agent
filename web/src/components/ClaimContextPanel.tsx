/**
 * What the claim is worth, how old it is, and what a rep has corrected for this merchant
 * before.
 *
 * These are facts the service works out once, up front, so that nothing later has to work
 * them out again. The screen prints them and adds nothing: in particular the order value
 * arrives already worked out, and the line items further down the page are deliberately
 * never added up here.
 */
import { formatDayCount, formatMoment, formatMoney } from "../display";
import type { ClaimContext } from "../api/types";

interface ClaimContextPanelProps {
  context: ClaimContext;
}

export function ClaimContextPanel({ context }: ClaimContextPanelProps): React.JSX.Element {
  const corrections = context.merchant_corrections;

  return (
    <section className="panel">
      <h3 className="panel-title">The claim in numbers</h3>

      <div className="facts">
        <Fact label="Order value">
          {formatMoney(context.order_value_usd)}
          {context.order_value_usd === null && (
            <span className="fact-caveat">the order could not be read</span>
          )}
        </Fact>

        <Fact label="High value">
          {context.is_high_value ? "Yes" : "No"}
          {!context.is_high_value && context.order_value_usd === null && (
            <span className="fact-caveat">not known to be, with no value to compare</span>
          )}
        </Fact>

        <Fact label="Filed after delivery">
          {formatDayCount(context.days_since_delivery)}
          <span className="fact-caveat">delivery to the day the claim was opened</span>
        </Fact>

        <Fact label="Delivered">{formatMoment(context.delivered_date)}</Fact>
      </div>

      <h4 className="subhead">What a rep corrected before</h4>
      {corrections.length === 0 ? (
        <p className="empty">
          Nothing on file for this merchant. Either they are new to us, or none of their
          earlier claims needed correcting.
        </p>
      ) : (
        <ul className="corrections">
          {corrections.map((correction) => (
            <li key={`${correction.case_id}-${correction.recorded_at}`} className="correction">
              <p className="correction-summary">{correction.summary}</p>
              <p className="correction-meta">
                {correction.case_id} · {formatMoment(correction.recorded_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="fact">
      <span className="fact-label">{label}</span>
      <span className="fact-value">{children}</span>
    </div>
  );
}
