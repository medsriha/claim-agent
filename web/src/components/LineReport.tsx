/** Render the canonical report data. No report prose is supplied by the backend. */
import { formatDayCount, formatMoney, humanise } from "../display";
import type {
  Assessment,
  Attachment,
  ClarificationReportContent,
  ClaimContext,
  EvidenceFinding,
  InvestigationReportContent,
  Report,
  ScreeningReportContent,
} from "../api/types";

export function StructuredReport({ report }: { report: Report }): React.JSX.Element {
  if (report.content.kind === "investigation") {
    return <InvestigationContent content={report.content} />;
  }
  if (report.content.kind === "clarification") {
    return (
      <ClarificationContent
        content={report.content}
        recommendation={report.recommendation}
      />
    );
  }
  return <ScreeningContent content={report.content} />;
}

function ClarificationContent({
  content,
  recommendation,
}: {
  content: ClarificationReportContent;
  recommendation: Report["recommendation"];
}): React.JSX.Element {
  return (
    <div className="structured-report">
      <FindingsAndNextSteps finding={content.ambiguity} recommendation={recommendation} />

      {content.candidate_lines.length > 0 && (
        <details className="line-details">
          <summary className="line-details-summary">Possible products considered</summary>
          <h4 className="line-section">Possible products</h4>
          <ul className="line-list">
            {content.candidate_lines.map((line) => (
              <li key={line.claim_line_id}>{line.claimed.name}</li>
            ))}
          </ul>
        </details>
      )}

      {content.attachments.length > 0 && (
        <details className="line-details">
          <summary className="line-details-summary">
            Claim images ({String(content.attachments.length)})
          </summary>
          <AttachmentGallery attachments={content.attachments} />
        </details>
      )}

      <ReportContext context={content.context} correctionsConsidered={[]} />
    </div>
  );
}

function InvestigationContent({
  content,
}: {
  content: InvestigationReportContent;
}): React.JSX.Element {
  const { outcome, amount, evidence, assessments, concerns } = content;
  const overruled = outcome.recommendation !== outcome.recommended_by_agent;

  return (
    <div className="structured-report">
      {overruled && (
        <p className="line-overruled">
          The investigation recommended <strong>{humanise(outcome.recommended_by_agent)}</strong>.
          {outcome.overrides.length > 0 &&
            ` The rules that stepped in: ${outcome.overrides.map(humanise).join(", ")}.`}
        </p>
      )}

      <FindingsAndNextSteps
        finding={content.finding_summary ?? outcome.explanation}
        recommendation={outcome.recommendation}
      />

      {concerns.length > 0 && (
        <details className="line-details">
          <summary className="line-details-summary">
            Concerns ({String(concerns.length)})
          </summary>
          <ul className="line-list">
            {concerns.map((concern) => (
              <li key={concern}>{concern}</li>
            ))}
          </ul>
        </details>
      )}

      <ReportContext
        context={content.context}
        correctionsConsidered={content.corrections_considered}
      />
      <AmountWorking amount={amount} />

      <details className="line-details">
        <summary className="line-details-summary">Evidence and assessment details</summary>

        <AttachmentGallery attachments={content.attachments} />

        <h4 className="line-section">Evidence</h4>
        <ul className="line-evidence">
          {evidence.map((item) => (
            <EvidenceRow
              key={item.kind}
              item={item}
              url={
                content.attachments.find(
                  (attachment) => attachment.attachment_id === item.attachment_id,
                )?.url ?? null
              }
            />
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
            The four questions were not reached. That is not the same as answering no.
          </p>
        )}
      </details>
    </div>
  );
}

function FindingsAndNextSteps({
  finding,
  recommendation,
}: {
  finding: string;
  recommendation: Report["recommendation"];
}): React.JSX.Element {
  return (
    <section className="line-priority">
      <h4 className="line-section">Findings and next steps</h4>
      <p className="line-key-finding">{finding}</p>
      <p className="line-next-step">
        <strong>Next:</strong> {nextStepFor(recommendation)}
      </p>
    </section>
  );
}

function nextStepFor(recommendation: Report["recommendation"]): string {
  switch (recommendation) {
    case "approve":
      return "Review the recommendation and amount, then send the approval email if they are correct.";
    case "request_info":
      return "Send the drafted email, then resume the review when the merchant provides the missing or corrected information.";
    case "request_rep_clarification":
      return "Resolve the internal uncertainty before deciding whether the merchant needs to be contacted.";
    default:
      return "Review the findings and decide how the claim should proceed.";
  }
}

function AttachmentGallery({
  attachments,
}: {
  attachments: readonly Attachment[];
}): React.JSX.Element | null {
  if (attachments.length === 0) {
    return null;
  }

  return (
    <section className="report-images">
      <h4 className="line-section">Claim images</h4>
      <div className="report-image-grid">
        {attachments.map((attachment) => {
          const url = safeWebUrl(attachment.url);
          const name = attachment.file_name ?? attachment.attachment_id;
          return (
            <figure className="report-image-card" key={attachment.attachment_id}>
              {url === null ? (
                <div className="report-image-unavailable">Image URL unavailable</div>
              ) : (
                <a
                  className="report-image-link"
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open ${name} at full size`}
                >
                  <img
                    src={url}
                    alt={`Claim attachment ${name}`}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                </a>
              )}
              <figcaption>
                <span>{name}</span>
                <code>{attachment.attachment_id}</code>
                {url !== null && (
                  <a href={url} target="_blank" rel="noreferrer">
                    Open full size
                  </a>
                )}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}

/** Only web URLs become image sources or clickable links. */
function safeWebUrl(raw: string): string | null {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function ScreeningContent({
  content,
}: {
  content: ScreeningReportContent;
}): React.JSX.Element {
  return (
    <div className="structured-report">
      {content.requires_rep_clarification && (
        <p className="line-overruled">The representative must clarify how this claim proceeds.</p>
      )}

      <section className="line-concerns">
        <h4 className="line-section">Why the claim was stopped</h4>
        <ul className="line-list">
          {content.reasons.map((reason) => (
            <li key={reason}>{humanise(reason)}</li>
          ))}
        </ul>
      </section>

      {content.findings.length > 0 && (
        <details className="line-details">
          <summary className="line-details-summary">Screening findings</summary>
          <ul className="line-list">
            {content.findings.map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        </details>
      )}

      <ReportContext context={content.context} correctionsConsidered={[]} />

      <details className="line-details">
        <summary className="line-details-summary">The four eligibility checks</summary>
        <ul className="line-assessments">
          {content.gates.map((gate) => (
            <li
              className={gate.passed ? "judgement judgement-yes" : "judgement judgement-no"}
              key={gate.gate}
            >
              <span className="judgement-name">{humanise(gate.gate)}</span>
              <span className="judgement-answer">{gate.passed ? "Passed" : "Stopped"}</span>
              <span className="judgement-reasoning">{gate.explanation}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function ReportContext({
  context,
  correctionsConsidered,
}: {
  context: ClaimContext;
  correctionsConsidered: readonly string[];
}): React.JSX.Element {
  return (
    <details className="line-details">
      <summary className="line-details-summary">The claim in context</summary>
      <dl className="amount-steps">
        <div className="amount-step">
          <dt>Order value</dt>
          <dd>{formatMoney(context.order_value_usd)}</dd>
        </div>
        <div className="amount-step">
          <dt>Filed after delivery</dt>
          <dd>{formatDayCount(context.days_since_delivery)}</dd>
        </div>
        <div className="amount-step">
          <dt>High-value order</dt>
          <dd>{context.is_high_value ? "Yes" : "No"}</dd>
        </div>
      </dl>

      <h4 className="line-section">Past corrections for this merchant</h4>
      {context.merchant_corrections.length === 0 ? (
        <p className="line-none">None on file.</p>
      ) : (
        <ul className="line-list">
          {context.merchant_corrections.map((correction) => (
            <li key={`${correction.case_id}-${correction.recorded_at}`}>
              {correction.case_id}: {correction.summary}
              {correctionsConsidered.includes(correction.case_id) && " (changed this conclusion)"}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function AmountWorking({
  amount,
}: {
  amount: InvestigationReportContent["amount"];
}): React.JSX.Element {
  return (
    <details className="amount-working">
      <summary className="amount-summary">How the amount was worked out</summary>

      {amount.components.length === 0 ? (
        <p className="line-none">
          Nothing could be priced for this product
          {amount.priced_from === null
            ? ", because no invoice could be obtained."
            : ` from invoice ${amount.priced_from}.`}
        </p>
      ) : (
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
      )}

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
          <dt>{amount.cap_applied ? "Brought down to the cap" : "Recommended amount"}</dt>
          <dd>{formatMoney(amount.amount_usd)}</dd>
        </div>
      </dl>

      {amount.reasoning !== "" && <p className="amount-reasoning">{amount.reasoning}</p>}
      {amount.priced_from !== null && (
        <p className="amount-source">Priced from invoice {amount.priced_from}.</p>
      )}
    </details>
  );
}

function EvidenceRow({
  item,
  url,
}: {
  item: EvidenceFinding;
  url: string | null;
}): React.JSX.Element {
  const sourceUrl = url === null ? null : safeWebUrl(url);
  return (
    <li className={`evidence evidence-${item.state}`}>
      <span className="evidence-kind">{humanise(item.kind)}</span>
      <span className="evidence-state">{humanise(item.state)}</span>
      <span className="evidence-observed">{item.observed}</span>
      {item.problem !== null && <span className="evidence-problem">{item.problem}</span>}
      {item.attachment_id !== null && (
        <span className="evidence-source">
          {sourceUrl === null ? (
            item.attachment_id
          ) : (
            <a href={sourceUrl} target="_blank" rel="noreferrer">
              {item.attachment_id}
            </a>
          )}
        </span>
      )}
    </li>
  );
}

function AssessmentRow({ judgement }: { judgement: Assessment }): React.JSX.Element {
  return (
    <li className={judgement.passed ? "judgement judgement-yes" : "judgement judgement-no"}>
      <span className="judgement-name">{humanise(judgement.name)}</span>
      <span className="judgement-answer">{judgement.passed ? "Yes" : "No"}</span>
      <span className="judgement-reasoning">{judgement.reasoning}</span>
    </li>
  );
}
