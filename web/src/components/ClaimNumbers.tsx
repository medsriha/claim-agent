import { formatDayCount, formatMoment, formatMoney } from "../display";
import type { ClaimContext } from "../api/types";

export function ClaimNumbers({ context }: { context: ClaimContext }): React.JSX.Element {
  const corrections = context.merchant_corrections;

  return (
    <>
      <div className="facts">
        <Fact label="Order value">{formatMoney(context.order_value_usd)}</Fact>
        <Fact label="High value">{context.is_high_value ? "Yes" : "No"}</Fact>
        <Fact label="Filed after delivery">{formatDayCount(context.days_since_delivery)}</Fact>
        <Fact label="Delivered">{formatMoment(context.delivered_date)}</Fact>
      </div>

      <h4 className="subhead">Past rep corrections</h4>
      {corrections.length === 0 ? (
        <p className="empty">None on file for this merchant.</p>
      ) : (
        <ul className="corrections">
          {corrections.map((correction) => (
            <li key={`${correction.case_id}-${correction.recorded_at}`} className="correction">
              <p>{correction.summary}</p>
              <p className="correction-meta">
                {correction.case_id} · {formatMoment(correction.recorded_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </>
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
