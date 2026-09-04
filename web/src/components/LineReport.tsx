/**
 * Everything established about one damaged product — the thing a representative decides on.
 *
 * Four parts, in the order somebody reads them: what is recommended, how the money was
 * arrived at, what the evidence showed, and what the four judgements were. The concerns come
 * first among the details, because a representative who cannot see why the system is unsure
 * will either rubber-stamp it or redo the work.
 *
 * **Nothing here is worked out on screen.** Every figure is text the service sent, and the
 * arithmetic between the figures was done in the service — showing the steps is not the same
 * as doing them, and doing them again here would be a second calculation that could disagree
 * with the first.
 *
 * **A recommendation is not a decision.** It says what the system suggests and why. Nothing
 * on this screen can send an email or move money, and there is deliberately no control here
 * that looks as though it could.
 */
import { formatMoney, humanise } from "../display";
import type { Assessment, EvidenceFinding, LineInvestigation } from "../api/types";

interface LineReportProps {
  report: LineInvestigation;
  position: number;
  outOf: number;
}

export function LineReport({ report, position, outOf }: LineReportProps): React.JSX.Element {
  const { line, outcome, amount, evidence, assessments, concerns } = report;
  const overruled = outcome.recommendation !== outcome.recommended_by_agent;

  return (
    <div className={`line-report line-${outcome.recommendation}`}>
      <div className="line-heading">
        <p className="line-count">
          Product {String(position)} of {String(outOf)}
        </p>
        <h3 className="line-product">{line.claimed.name}</h3>
        {line.claimed.sku !== null && <p className="line-sku">{line.claimed.sku}</p>}
      </div>

      <p className="line-recommendation">
        <span className="line-verdict">{humanise(outcome.recommendation)}</span>
        {outcome.recommendation === "approve" && (
          <span className="line-amount">{formatMoney(amount.amount_usd)}</span>
        )}
      </p>

      <p className="line-explanation">{outcome.explanation}</p>

      {/* Shown whenever the rules did not leave the investigation's own answer standing. A
          representative should be able to see that a product was sound on its own evidence
          and that a rule withheld the payment anyway. */}
      {overruled && (
        <p className="line-overruled">
          The investigation itself recommended{" "}
          <strong>{humanise(outcome.recommended_by_agent)}</strong>.
          {outcome.overrides.length > 0 &&
            ` The rules that stepped in: ${outcome.overrides.map(humanise).join(", ")}.`}
        </p>
      )}

      {concerns.length > 0 && (
        <div className="line-concerns">
          <h4 className="line-section">Concerns</h4>
          <ul className="line-list">
            {concerns.map((concern) => (
              <li key={concern}>{concern}</li>
            ))}
          </ul>
        </div>
      )}

      <AmountWorking amount={report.amount} />

      <details className="line-details">
        <summary className="line-details-summary">The evidence and the four questions</summary>

        <h4 className="line-section">Evidence</h4>
        <ul className="line-evidence">
          {evidence.map((item) => (
            <EvidenceRow key={item.kind} item={item} />
          ))}
        </ul>

        {assessments.length > 0 ? (
          <>
            <h4 className="line-section">The four questions</h4>
            <ul className="line-assessments">
              {assessments.map((judgement) => (
                <AssessmentRow key={judgement.name} judgement={judgement} />
              ))}
            </ul>
          </>
        ) : (
          <p className="line-none">
            The four questions were not reached: they are only asked once every piece of
            evidence is in hand.
          </p>
        )}
      </details>
    </div>
  );
}

/**
 * How the figure was arrived at (FR-2.4).
 *
 * A bare amount is not reviewable. This shows what the investigation judged the damage to
 * be worth, what those items cost for comparison, whether the cap brought it down, and why
 * it settled on that figure — every one of them sent by the service.
 *
 * The amount is a judgement now rather than a sum, so the reasoning is the part that makes
 * it reviewable at all: there is no arithmetic for a representative to redo.
 *
 * Drawn even where nothing is payable, because "why nothing?" is exactly the question a
 * representative asks of a product that was not approved.
 */
function AmountWorking({ amount }: { amount: LineInvestigation["amount"] }): React.JSX.Element {
  return (
    <details className="amount-working">
      <summary className="amount-summary">How the amount was worked out</summary>

      {amount.components.length === 0 ? (
        <p className="line-none">
          Nothing could be priced for this product
          {amount.priced_from === null
            ? ", because no invoice could be had."
            : `, from invoice ${amount.priced_from}.`}
        </p>
      ) : (
        <>
          <ul className="amount-items">
            {amount.components.map((item) => (
              <li key={`${item.product_name}-${item.sku ?? ""}`} className="amount-item">
                <span className="amount-item-name">
                  {String(item.quantity)} × {item.product_name}
                </span>
                <span className="amount-item-price">{formatMoney(item.unit_price)} each</span>
              </li>
            ))}
          </ul>

          <dl className="amount-steps">
            <div className="amount-step">
              <dt>What the investigation judged it worth</dt>
              <dd>{formatMoney(amount.proposed_usd)}</dd>
            </div>
            <div className="amount-step">
              <dt>What those items cost</dt>
              <dd>{formatMoney(amount.items_total_usd)}</dd>
            </div>
            <div className="amount-step">
              <dt>{amount.cap_applied ? "Brought down to the cap" : "Under the cap of"}</dt>
              <dd>{formatMoney(amount.cap_applied ? amount.amount_usd : amount.cap_usd)}</dd>
            </div>
          </dl>

          {/* The whole justification for the figure, now that it is a judgement rather
              than a sum a representative could redo. */}
          {amount.reasoning !== "" && <p className="amount-reasoning">{amount.reasoning}</p>}

          {amount.priced_from !== null && (
            <p className="amount-source">Priced from invoice {amount.priced_from}.</p>
          )}
        </>
      )}
    </details>
  );
}

/** One piece of evidence: whether it can be relied on, and what was seen. */
function EvidenceRow({ item }: { item: EvidenceFinding }): React.JSX.Element {
  return (
    <li className={`evidence evidence-${item.state}`}>
      <span className="evidence-kind">{humanise(item.kind)}</span>
      <span className="evidence-state">{humanise(item.state)}</span>
      <span className="evidence-observed">{item.observed}</span>
      {/* Only ever set where the evidence cannot be relied on, and it is the sentence a
          merchant would be asked to act on — so it is shown rather than tucked away. */}
      {item.problem !== null && <span className="evidence-problem">{item.problem}</span>}
      {item.attachment_id !== null && (
        <span className="evidence-source">{item.attachment_id}</span>
      )}
    </li>
  );
}

/**
 * One of the four judgements, with its reasoning and how sure it was.
 *
 * The confidence is shown rather than only being compared against a threshold: a number a
 * representative can see is worth more than a gate they cannot. It is the system's own
 * opinion of itself and nothing has checked it against what turned out to be true.
 */
function AssessmentRow({ judgement }: { judgement: Assessment }): React.JSX.Element {
  return (
    <li className={judgement.passed ? "judgement judgement-yes" : "judgement judgement-no"}>
      <span className="judgement-name">{humanise(judgement.name)}</span>
      <span className="judgement-answer">{judgement.passed ? "Yes" : "No"}</span>
      <span className="judgement-confidence">
        {String(Math.round(judgement.confidence * 100))}% sure
      </span>
      <span className="judgement-reasoning">{judgement.reasoning}</span>
    </li>
  );
}
