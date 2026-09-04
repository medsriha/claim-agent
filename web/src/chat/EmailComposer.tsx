/**
 * The drafted email to the merchant, which a representative can reword and send.
 *
 * Two things about it are worth knowing before you read the code.
 *
 * **The send is a simulation.** Pressing it changes nothing outside this browser. There is
 * no address in the service behind it, because the stage that would really send an email
 * has not been built. So the screen says outright, once it is pressed, that nothing was
 * sent — a button that looks like it sends is too dangerous to leave unexplained.
 *
 * **The recipient cannot be edited.** It comes from the contact address on the claim. A
 * representative changes the wording; who hears about it is not theirs to change. A claim
 * with no contact address gives an email with nobody to send it to, and the button is
 * unavailable rather than merely unwise — that is the rule the real sending stage will have
 * to follow, so this follows it now.
 */
import { useState } from "react";

import { PAGE_WORDS } from "./pageWords";
import type { DraftedEmail } from "../api/types";

/** The smallest the wording box gets, so a short email still looks like an email. */
const SMALLEST_BODY_ROWS = 8;

export function EmailComposer({ email }: { email: DraftedEmail }): React.JSX.Element {
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [sent, setSent] = useState(false);

  const recipient = email.to;

  if (sent) {
    return (
      <div className="composer">
        <div className="email">
          <div className="email-headers">
            <EmailHeader label="To">{recipient}</EmailHeader>
            <EmailHeader label="Subject">{subject}</EmailHeader>
          </div>
          {/* Line breaks are kept so the wording reads exactly as it stands. */}
          <div className="email-body">{body}</div>
        </div>
        <p className="note note-inline" role="status">
          {PAGE_WORDS.nothingWasSent}
        </p>
      </div>
    );
  }

  return (
    <div className="composer">
      <p className="draft-warning">
        <strong>Draft — not sent.</strong> Waits for a rep to approve it.
      </p>

      <div className="email">
        <div className="email-headers">
          <EmailHeader label="To">
            {recipient ?? <span className="email-missing">no contact address on the case</span>}
          </EmailHeader>
        </div>

        <div className="composer-field">
          <label className="composer-label" htmlFor="email-subject">
            Subject
          </label>
          <input
            id="email-subject"
            className="composer-subject"
            type="text"
            value={subject}
            onChange={(event) => {
              setSubject(event.target.value);
            }}
          />
        </div>

        <div className="composer-field">
          <label className="composer-label" htmlFor="email-body">
            Wording
          </label>
          <textarea
            id="email-body"
            className="composer-body"
            // Grown to fit rather than measured, which needs no layout reading and cannot
            // disagree with what the browser actually renders.
            rows={Math.max(SMALLEST_BODY_ROWS, body.split("\n").length + 1)}
            value={body}
            onChange={(event) => {
              setBody(event.target.value);
            }}
          />
        </div>
      </div>

      <div className="composer-actions">
        <button
          className="button-primary"
          type="button"
          disabled={recipient === null}
          onClick={() => {
            setSent(true);
          }}
        >
          Send to merchant
        </button>
        {recipient === null && (
          <span className="composer-blocked">
            There is no address on this claim to send to.
          </span>
        )}
      </div>
    </div>
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
