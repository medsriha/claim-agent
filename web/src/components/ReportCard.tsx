/** One structured report a representative reads and decides on. */
import { useState } from "react";

import { approveReport, sendReportBack } from "../api/reportsClient";
import { ApiFailure } from "../api/failure";
import type { DraftedEmail, Report, ReportReview } from "../api/types";
import { formatMoney, humanise } from "../display";
import { PAGE_WORDS } from "../chat/pageWords";
import { StructuredReport } from "./LineReport";
import { Spinner } from "./Spinner";

type Busy = "approving" | "sending back" | null;

interface ReportCardProps {
  report: Report;
  /** Set when the structured findings arrived but could not be persisted. */
  unavailableReason: string | null;
}

export function ReportCard({ report, unavailableReason }: ReportCardProps): React.JSX.Element {
  const [current, setCurrent] = useState(report);
  const [subject, setSubject] = useState(report.drafted_email?.subject ?? "");
  const [body, setBody] = useState(report.drafted_email?.body ?? "");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<Busy>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const settled = current.state === "approved";
  const email = current.drafted_email;
  const reworded = email !== null && (subject !== email.subject || body !== email.body);

  const act = async (what: Busy, run: () => Promise<Report>): Promise<void> => {
    setBusy(what);
    setProblem(null);
    try {
      const answered = await run();
      setCurrent(answered);
      setSubject(answered.drafted_email?.subject ?? "");
      setBody(answered.drafted_email?.body ?? "");
      setFeedback("");
    } catch (error: unknown) {
      setProblem(
        error instanceof ApiFailure
          ? error.message
          : "This screen ran into a problem of its own.",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="report-card">
      <ReportHeading report={current} />
      <div className="report-document">
        <StructuredReport report={current} />
      </div>

      <ReviewHistory reviews={current.reviews} />

      {email === null ? (
        <p className="report-note">No merchant email was produced for this report.</p>
      ) : settled || unavailableReason !== null ? (
        <ReadOnlyEmail email={email} />
      ) : (
        <EditableEmail
          email={email}
          subject={subject}
          body={body}
          onSubject={setSubject}
          onBody={setBody}
        />
      )}

      {unavailableReason !== null ? (
        <p className="report-problem">{unavailableReason}</p>
      ) : settled ? (
        <p className="report-settled">
          Approved. {PAGE_WORDS.nothingActsOnAnApproval}
        </p>
      ) : (
        <div className="report-actions">
          <label className="report-field">
            <span>A note, if you are sending this back</span>
            <textarea
              className="report-body"
              rows={3}
              value={feedback}
              onChange={(event) => {
                setFeedback(event.target.value);
              }}
            />
          </label>

          <div className="report-buttons">
            <button
              type="button"
              className="button-primary"
              disabled={busy !== null}
              onClick={() =>
                void act("approving", () =>
                  approveReport(current.report_id, {
                    ...(reworded ? { email: { subject, body } } : {}),
                  }),
                )
              }
            >
              {busy === "approving" ? <Spinner /> : null}
              {reworded ? "Reword and approve" : "Approve"}
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={busy !== null || feedback.trim() === ""}
              onClick={() =>
                void act("sending back", () => sendReportBack(current.report_id, feedback))
              }
            >
              {busy === "sending back" ? <Spinner /> : null}
              Send back
            </button>
          </div>

          <p className="report-note">{PAGE_WORDS.nothingActsOnAnApproval}</p>
        </div>
      )}

      {problem !== null && <p className="report-problem">{problem}</p>}
    </article>
  );
}

function EditableEmail({
  email,
  subject,
  body,
  onSubject,
  onBody,
}: {
  email: DraftedEmail;
  subject: string;
  body: string;
  onSubject: (value: string) => void;
  onBody: (value: string) => void;
}): React.JSX.Element {
  return (
    <fieldset className="report-email">
      <legend>The merchant&rsquo;s email</legend>
      <label className="report-field">
        <span>To</span>
        <output>{email.to ?? "no address on this claim"}</output>
      </label>
      <label className="report-field">
        <span>Subject</span>
        <input
          className="lookup-input"
          value={subject}
          onChange={(event) => {
            onSubject(event.target.value);
          }}
        />
      </label>
      <label className="report-field">
        <span>Wording</span>
        <textarea
          className="report-body"
          rows={8}
          value={body}
          onChange={(event) => {
            onBody(event.target.value);
          }}
        />
      </label>
    </fieldset>
  );
}

function ReadOnlyEmail({ email }: { email: DraftedEmail }): React.JSX.Element {
  return (
    <section className="report-email">
      <h4>The merchant&rsquo;s email</h4>
      <p className="report-field">
        <span>To</span>
        <output>{email.to ?? "no address on this claim"}</output>
      </p>
      <p className="report-field">
        <span>Subject</span>
        <output>{email.subject}</output>
      </p>
      <p className="report-field">
        <span>Wording</span>
        <output className="email-body">{email.body}</output>
      </p>
    </section>
  );
}

function ReviewHistory({ reviews }: { reviews: readonly ReportReview[] }): React.JSX.Element | null {
  if (reviews.length === 0) {
    return null;
  }
  return (
    <section className="report-reviews">
      <h4>Review history</h4>
      <ol>
        {reviews.map((review) => (
          <li key={review.review_number}>
            <strong>{humanise(review.action)}</strong>
            {review.rep_words !== null && ` — ${review.rep_words}`}
            {review.over_the_cap_by !== null &&
              ` — ${formatMoney(review.over_the_cap_by)} over the recommendation cap`}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ReportHeading({ report }: { report: Report }): React.JSX.Element {
  return (
    <header className="report-heading">
      <p className="line-count">
        Claim {report.case_id}
        {report.account_name === null ? "" : ` · ${report.account_name}`}
      </p>
      <h3>{report.product_name ?? "This claim"}</h3>
      <p>
        {report.recommendation === null ? (
          <span>Stopped before investigation</span>
        ) : (
          <span className={`report-recommendation is-${report.recommendation}`}>
            {humanise(report.recommendation)}
          </span>
        )}
        {report.amount_usd !== null && report.recommendation === "approve" && (
          <span className="report-amount">{formatMoney(report.amount_usd)}</span>
        )}
        {report.confidence !== null && (
          <span className="report-confidence">
            {String(Math.round(report.confidence * 100))}% confidence
          </span>
        )}
        <span className={`report-state is-${report.state}`}>{humanise(report.state)}</span>
      </p>
      {report.decided !== null && report.decided.amount_usd !== report.amount_usd && (
        <p className="report-decided">
          Approved at {formatMoney(report.decided.amount_usd)}, which is not what was advised.
        </p>
      )}
    </header>
  );
}
