/**
 * The past claims that resemble the one on screen, and why the service thought so.
 *
 * Everything here came from the service: the ranking, the reasons, the outcome each past
 * claim reached, and what a representative said about it. The screen adds labels, and
 * decides only what to show first.
 *
 * **Each claim is folded shut.** Open, it shows which claim, which product and what it
 * closed on — the least a representative needs to judge whether this claim is being handled
 * consistently. The reasons, the other merchant's account and the representative's note
 * wait behind the fold, because five past claims each unfolded is a wall of text standing
 * in front of the claim actually being decided.
 *
 * **Every claim shown here was closed by a representative.** The service stores nothing
 * that is still in review, because a claim nobody has decided has no outcome to learn from.
 * So there is no weaker sort of record to mark out, and none of these needs a caveat.
 */
import { PAGE_WORDS } from "../chat/pageWords";
import { formatMoney, humanise } from "../display";
import type { PrecedentSet, RetrievedPrecedent } from "../api/types";

interface SimilarClaimsProps {
  /** What the search found. `null` when the request itself never got an answer. */
  found: PrecedentSet | null;
  /** Why nothing could be looked up, in the service's own words. `null` when it could. */
  failureMessage: string | null;
}

export function SimilarClaims({ found, failureMessage }: SimilarClaimsProps): React.JSX.Element {
  // Nobody managed to look. Deliberately not shown as "none found": telling a
  // representative there is no comparable history, when in fact the store could not be
  // read, is the one answer here that would mislead them.
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

/**
 * One closed claim, folded shut.
 *
 * **A representative scanning this wants the shortest thing that lets them judge
 * consistency**: which claim, which product, and what it closed on. Everything else is
 * behind the fold, because five past claims each showing their full history is a wall of
 * text in front of the claim actually being decided.
 *
 * Uses the page's own fold rather than anything of ours, the same as a check card does. It
 * needs no state, no library, and it opens with a keyboard.
 */
function SimilarClaim({ found }: { found: RetrievedPrecedent }): React.JSX.Element {
  const { record, similarity } = found;

  return (
    <li className="similar">
      <details>
        <summary className="similar-summary">
          <span className="similar-case">{record.case_id}</span>
          <span className="similar-product">{record.product_name}</span>
          {/* What the claim actually closed on — a decision, not a suggestion, because the
              service stores nothing that is still in review. */}
          <span className="similar-closed">
            {humanise(record.outcome)}
            {/* Shown only where there is one. A claim that closed without paying carries no
                figure, and printing "unknown" beside it would suggest one was expected. The
                text is the service's own and no arithmetic is done on it. */}
            {record.amount_usd !== null && ` ${formatMoney(record.amount_usd)}`}
          </span>
        </summary>

        <div className="similar-more">
          {/* Why the service put this claim in front of the rep. Its own sentences, so the
              comparison can be disagreed with rather than taken on trust. */}
          {similarity.reasons.length > 0 && (
            <ul className="similar-reasons">
              {similarity.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}

          {/* The other merchant's own account of what happened, shown the same way the
              claim on screen shows theirs. */}
          {record.merchant_account !== null && (
            <blockquote className="description">{record.merchant_account}</blockquote>
          )}

          {/* What the representative said about the decision, where they said anything.
              This is the part a later claim actually learns from. */}
          {record.rep_note !== null && <p className="similar-note">{record.rep_note}</p>}
        </div>
      </details>
    </li>
  );
}
