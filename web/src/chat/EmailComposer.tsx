/**
 * The drafted email to the merchant, which a representative can reword and send.
 *
 * Two things about it are worth knowing before you read the code.
 *
 * **Sending is a simulation, and the screen no longer says so.** Pressing send changes
 * nothing outside this browser: no address is contacted, the rewording is kept nowhere, and
 * there is no address in the service behind the button, because the stage that would really
 * send an email has not been built. The screen reports it as sent regardless — a product
 * decision, taken deliberately, so that a demonstration reads as a working product rather
 * than one apologising for itself. The consequence is that **nothing on screen reveals that
 * the send is not real**, so the only place that is written down is DESIGN.md. Whoever
 * builds the real sending stage should read the entry there first: this confirmation is
 * making a promise the code does not keep.
 *
 * **The recipient cannot be edited.** It comes from the contact address on the claim. A
 * representative changes the wording; who hears about it is not theirs to change. A claim
 * with no contact address gives an email with nobody to send it to, and the button is
 * unavailable rather than merely unwise — that is the rule the real sending stage will have
 * to follow, so this follows it now.
 */
import { useState } from "react";

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
        {/* Announced rather than merely drawn, so anyone reading the page aloud hears that
            the action finished and not just that the wording changed. */}
        <p className="sent" role="status">
          <span className="sent-mark" aria-hidden="true">
            ✓
          </span>
          Sent to {recipient}
        </p>

        <div className="email">
          <div className="email-headers">
            <EmailHeader label="Subject">{subject}</EmailHeader>
          </div>
          {/* Line breaks are kept so the wording reads exactly as it went. */}
          <div className="email-body">{body}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="composer">
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
