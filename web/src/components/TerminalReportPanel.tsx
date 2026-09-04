/**
 * What a rep acts on when a claim is stopped: what was found, and the email about it.
 *
 * The email is marked as a draft here because its own words never say so — deliberately,
 * so a marker cannot reach a merchant. There is no send button and nothing behind one.
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
      <h3 className="panel-title">What was found</h3>
      <ul className="findings">
        {report.findings.map((finding) => (
          <li key={finding}>{finding}</li>
        ))}
      </ul>

      <h4 className="subhead">Email to the merchant</h4>
      <p className="draft-warning">
        <strong>Draft — not sent.</strong> Waits for a rep to approve it.
      </p>

      <article className="email">
        <div className="email-headers">
          <EmailHeader label="To">
            {email.to ?? <span className="email-missing">no contact address on the case</span>}
          </EmailHeader>
          <EmailHeader label="Subject">{email.subject}</EmailHeader>
        </div>
        {/* Line breaks are kept so a rep reads the exact words that would be sent. */}
        <div className="email-body">{email.body}</div>
      </article>
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

/** When the screening ran. Sits under the result. */
export function EvaluatedAt({ moment }: { moment: string }): React.JSX.Element {
  return <p className="evaluated">Screened {formatMoment(moment)}</p>;
}
