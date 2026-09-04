/**
 * The other thing a representative can do with a stopped claim: send it somewhere else.
 *
 * An insured shipment is claimed on its insurance, through a process that is not this
 * one, so nobody writes to the merchant about it — the claim is routed out for someone
 * else to pick up. The reason is already on screen in the system's own words, in the
 * findings just above, so this adds a button and no commentary.
 *
 * **Escalating is a simulation, in the same way sending is.** Nothing leaves the browser:
 * no queue, no ticket, nobody told. The screen reports it as escalated regardless, which
 * is the same product decision taken for the send — a demonstration reads as a working
 * product rather than one apologising for itself — and it carries the same consequence:
 * nothing on screen reveals that the escalation is not real. DESIGN.md is the only place
 * that is written down. Whoever builds the stage that really routes a claim out should
 * read that entry first.
 *
 * Where an escalation should actually go is not decided anywhere. The service says a
 * claim has to be escalated and says nothing about to whom, so neither does this — a
 * team name invented on screen would read exactly like one the service had chosen.
 */
import { useState } from "react";

export function EscalationAction(): React.JSX.Element {
  const [escalated, setEscalated] = useState(false);

  if (escalated) {
    return (
      // Announced rather than merely drawn, so anyone reading the page aloud hears that
      // the action finished.
      <p className="sent" role="status">
        <span className="sent-mark" aria-hidden="true">
          ✓
        </span>
        Escalated
      </p>
    );
  }

  return (
    <div className="composer-actions">
      <button
        className="button-primary"
        type="button"
        onClick={() => {
          setEscalated(true);
        }}
      >
        Escalate this claim
      </button>
    </div>
  );
}
