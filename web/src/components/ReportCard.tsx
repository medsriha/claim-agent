/**
 * One report a representative reads and decides on.
 *
 * The report itself is a written document the service produced, drawn as it was written. This
 * screen adds no sentences of its own to it and takes nothing out of it: the wording of the
 * merchant's email is offered for rewording as a field the service sent separately, never by
 * reading it back out of the writing.
 *
 * **Three things a representative can do**, and all three reach the service (FR-2.8):
 * approve it as it stands, reword the email first and then approve, or send it back with a note.
 * None of them sends an email or moves money — the stage that would act on an approval does not
 * exist, and this screen says so in the one sentence it owns.
 *
 * **No money is worked out here.** Every figure is text the service sent, shown as it arrived.
 */
import { useState } from "react";

import { approveReport, sendReportBack } from "../api/reportsClient";
import { ApiFailure } from "../api/failure";
import type { Report } from "../api/types";
import { PAGE_WORDS } from "../chat/pageWords";
import { Markdown } from "./Markdown";
import { Spinner } from "./Spinner";

/** What a review action is doing, so a button cannot be pressed twice while it works. */
type Busy = "approving" | "sending back" | null;

export function ReportCard({ report }: { report: Report }): React.JSX.Element {
  const [current, setCurrent] = useState(report);
  const [subject, setSubject] = useState(report.drafted_email?.subject ?? "");
  const [body, setBody] = useState(report.drafted_email?.body ?? "");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<Busy>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const settled = current.state === "approved";
  const email = current.drafted_email;
  const reworded =
    email !== null && (subject !== email.subject || body !== email.body);

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
        <Markdown text={current.markdown} />
      </div>

      {settled ? (
        <p className="report-settled">
          Approved. {PAGE_WORDS.nothingActsOnAnApproval}
        </p>
      ) : (
        <div className="report-actions">
          {email !== null && (
            <fieldset className="report-email">
              <legend>The merchant&rsquo;s email</legend>
              <label className="report-field">
                <span>To</span>
                {/* Not editable: who hears about a claim comes from the claim itself. */}
                <output>{email.to ?? "no address on this claim"}</output>
              </label>
              <label className="report-field">
                <span>Subject</span>
                <input
                  className="lookup-input"
                  value={subject}
                  onChange={(event) => {
                    setSubject(event.target.value);
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
                    setBody(event.target.value);
                  }}
                />
              </label>
            </fieldset>
          )}

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

/**
 * The line above a report: which product it covers, what is recommended, and where it has got to.
 *
 * Every value is the service's own, reshaped to read — `request_info` becomes "request info" —
 * never swapped for wording of ours.
 */
function ReportHeading({ report }: { report: Report }): React.JSX.Element {
  return (
    <header className="report-heading">
      <h3>{report.product_name ?? "This claim"}</h3>
      <p>
        {report.recommendation === null ? (
          <span>Stopped before investigation</span>
        ) : (
          <span className={`report-recommendation is-${report.recommendation}`}>
            {inWords(report.recommendation)}
          </span>
        )}
        {report.amount_usd !== null && report.recommendation === "approve" && (
          <span className="report-amount">${report.amount_usd}</span>
        )}
        <span className={`report-state is-${report.state}`}>{inWords(report.state)}</span>
      </p>
      {report.decided !== null && report.decided.amount_usd !== report.amount_usd && (
        <p className="report-decided">
          Approved at ${report.decided.amount_usd ?? "no amount"}, which is not what was advised.
        </p>
      )}
    </header>
  );
}

/** Write a stored name as words: `request_info` as "request info". Nothing is reworded. */
function inWords(name: string): string {
  const spaced = name.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
