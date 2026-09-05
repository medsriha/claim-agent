import { PAGE_WORDS } from "../chat/pageWords";
import { formatMoney, humanise } from "../display";
import type { PrecedentSet, RetrievedPrecedent } from "../api/types";

interface SimilarClaimsProps {
  found: PrecedentSet | null;
  failureMessage: string | null;
}

export function SimilarClaims({ found, failureMessage }: SimilarClaimsProps): React.JSX.Element {
  if (found === null || !found.was_read) {
    return (
      <p className="similar-unavailable">
        {failureMessage ?? found?.unavailable_reason ?? PAGE_WORDS.pastClaimsUnreadable}
      </p>
    );
  }

  if (found.retrieved.length === 0) {
    return <p className="similar-none">{PAGE_WORDS.noSimilarClaims}</p>;
  }

  return (
    <ol className="similar-list">
      {found.retrieved.map((one) => (
        <SimilarClaim key={one.record.precedent_id} found={one} />
      ))}
    </ol>
  );
}

function SimilarClaim({ found }: { found: RetrievedPrecedent }): React.JSX.Element {
  const { record, similarity } = found;

  return (
    <li className="similar">
      <details>
        <summary className="similar-summary">
          <span className="similar-case">{record.case_id}</span>
          <span className="similar-product">{record.product_name}</span>
          <span className="similar-closed">
            {humanise(record.outcome)}
            {record.amount_usd !== null && ` ${formatMoney(record.amount_usd)}`}
          </span>
        </summary>

        <div className="similar-more">
          {similarity.reasons.length > 0 && (
            <ul className="similar-reasons">
              {similarity.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}

          {record.merchant_account !== null && (
            <blockquote className="description">{record.merchant_account}</blockquote>
          )}

          {record.rep_note !== null && <p className="similar-note">{record.rep_note}</p>}
        </div>
      </details>
    </li>
  );
}
