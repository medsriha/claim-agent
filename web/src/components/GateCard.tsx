/**
 * One of the four eligibility checks: what it decided, and the values it looked at.
 *
 * It is drawn twice. First as **working** — its name, with something turning where its
 * answer will be — and then with the answer: a tick or a cross, the service's explanation,
 * and what the check read. The turning is the screen's own pacing and measures nothing; the
 * check itself had already run before any of this appeared.
 *
 * All four are always shown, whether they passed or failed. Showing the ones that passed
 * matters as much as the one that failed — a representative can see the insurance check ran
 * and cleared rather than inferring it from silence. Each card opens to reveal what the
 * check read, so a finding can be checked rather than merely trusted.
 */
import { Spinner } from "./Spinner";
import { humanise } from "../display";
import type { GateResult } from "../api/types";

interface GateCardProps {
  gate: GateResult;
  /** True while the card is standing in for a check that has not been reported yet. */
  working: boolean;
}

export function GateCard({ gate, working }: GateCardProps): React.JSX.Element {
  const observed = Object.entries(gate.observed);

  return (
    <div className={cardClass(gate, working)}>
      <div className="gate-head">
        <span className="gate-mark" aria-hidden="true">
          {working ? <Spinner /> : gate.passed ? "✓" : "✕"}
        </span>
        <h4 className="gate-name">{humanise(gate.gate)}</h4>
        <span className="gate-state">{stateWord(gate, working)}</span>
      </div>

      {/* Nothing below the heading until the check has been reported. A card that showed
          its answer while still turning would be saying two things at once. */}
      {!working && (
        <>
          <p className="gate-explanation">{gate.explanation}</p>

          {observed.length > 0 && (
            <details className="observed">
              <summary className="observed-summary">What it looked at</summary>
              <dl className="observed-list">
                {observed.map(([key, value]) => (
                  <div key={key} className="observed-row">
                    <dt className="observed-key">{humanise(key)}</dt>
                    {/* An empty value is a real answer here — "nothing was missing" — so it
                        is drawn rather than left as blank space that reads like a bug. */}
                    <dd className="observed-value">{value === "" ? "—" : value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function cardClass(gate: GateResult, working: boolean): string {
  if (working) {
    return "gate gate-working";
  }
  return gate.passed ? "gate gate-passed" : "gate gate-failed";
}

function stateWord(gate: GateResult, working: boolean): string {
  if (working) {
    return "Checking…";
  }
  return gate.passed ? "Passed" : "Failed";
}
