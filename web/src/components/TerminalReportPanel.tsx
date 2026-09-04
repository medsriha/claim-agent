/**
 * What a rep has to act on when a claim is stopped: what was found, and the email that
 * would go to the merchant about it.
 *
 * The email is shown as a draft, loudly and above the email itself. That is not
 * decoration. The email's own words never say "draft", deliberately, so that a marker
 * cannot reach a merchant by accident — which leaves this screen as the only place the
 * draft state is visible at all.
 *
 * There is no send button, and there is nothing behind one. Sending lives in a part of
 * the system that has not been built, and when it is built, it will only ever run after
 * a person has approved it.
 */
import { formatMoment } from "../display";
import type { TerminalReport } from "../api/types";

interface TerminalReportPanelProps {
  report: TerminalReport;
}

export function TerminalReportPanel({ report }: TerminalReportPanelProps): React.JSX.Element {
  const email = report.drafted_email;

  return (
    <section className="panel">
      <h3 className="panel-title">What happens next</h3>

      <h4 className="subhead">What was found</h4>
      <ul className="findings">
        {report.findings.map((finding) => (
          <li key={finding} className="finding">
            {finding}
          </li>
        ))}
      </ul>

      <h4 className="subhead">The email to the merchant</h4>
      <p className="draft-warning">
        <strong>Draft — not sent.</strong> Nothing here reaches the merchant until you approve
        it. This screen cannot send it, and there is nothing behind it that could.
      </p>

      <article className="email">
        <div className="email-headers">
          <EmailHeader label="To">
            {email.to ?? (
              <span className="email-missing">
                no contact address on the case — you will need to supply one
              </span>
            )}
          </EmailHeader>
          <EmailHeader label="Subject">{email.subject}</EmailHeader>
        </div>
        {/* The body arrives as paragraphs separated by blank lines. Keeping the line
            breaks is what lets a rep read the exact words that would be sent. */}
        <div className="email-body">{email.body}</div>
      </article>

      <dl className="report-meta">
        <div className="report-meta-row">
          <dt>Merchant</dt>
          <dd>{report.account_name ?? "not recorded"}</dd>
        </div>
        <div className="report-meta-row">
          <dt>Merchant account</dt>
          <dd>{report.user_id ?? "not recorded"}</dd>
        </div>
        <div className="report-meta-row">
          <dt>Approval</dt>
          {/* Always required. The service cannot send any other value, so there is no
              second case to handle here. */}
          <dd>Required before anything is sent</dd>
        </div>
      </dl>
    </section>
  );
}

function EmailHeader({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="email-header">
      <span className="email-header-label">{label}</span>
      <span className="email-header-value">{children}</span>
    </div>
  );
}

/**
 * Kept next to the report because it belongs to the same reading: when the screening ran.
 * Exported so the screen can put it in its footer without importing the date helper too.
 */
export function EvaluatedAt({ moment }: { moment: string }): React.JSX.Element {
  return <p className="evaluated">Screened {formatMoment(moment)}</p>;
}
