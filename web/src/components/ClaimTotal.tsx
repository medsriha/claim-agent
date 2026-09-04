/**
 * What a claim comes to across all of its products.
 *
 * Shown only where it says something a single product's report does not: a claim covering
 * more than one product, or one where the cap changed the answer. On a single product it
 * would be that product's figure written out twice.
 *
 * The cap is the one judgement no single product can make for itself — three products at
 * fifty dollars each are each within the limit and together are not — so it is the one
 * thing on screen that belongs to the claim rather than to a product. Where it bites,
 * nothing is trimmed and nothing is chosen between: every product recommended for payment
 * goes to a person, and the sentence explaining that is the service's own.
 *
 * The total is text the service sent and is never added up here.
 */
import { formatMoney } from "../display";

interface ClaimTotalProps {
  total: string;
  capApplied: boolean;
  /** The service's own sentences about the claim as a whole. Usually empty. */
  concerns: string[];
}

export function ClaimTotal({ total, capApplied, concerns }: ClaimTotalProps): React.JSX.Element {
  return (
    <div className={capApplied ? "claim-total claim-total-capped" : "claim-total"}>
      <p className="claim-total-line">
        <span className="claim-total-label">
          {capApplied ? "Recommended before the claim cap" : "Recommended across the claim"}
        </span>
        <span className="claim-total-figure">{formatMoney(total)}</span>
      </p>

      {concerns.map((concern) => (
        <p key={concern} className="claim-total-concern">
          {concern}
        </p>
      ))}
    </div>
  );
}
