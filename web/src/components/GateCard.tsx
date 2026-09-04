/**
 * One of the four eligibility checks: what it decided, and the values it looked at.
 *
 * It is drawn twice. First as **working** — its name, with something turning where its
 * answer will be — and then with the answer: a tick or a cross, the service's explanation,
 * and what the check read. The turning is the screen's own pacing and measures nothing; the
 * check itself had already run before any of this appeared.
 *
 * All four summaries are always shown, whether they passed or failed. Showing the ones that
 * passed matters as much as the one that failed — a representative can see the insurance
 * check ran and cleared rather than inferring it from silence. A settled card is collapsed
 * by default and opens to reveal its explanation and what the check read.
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

  if (working) {
    return (
      <div className={cardClass(gate, working)}>
        <GateHeading gate={gate} working />
      </div>
    );
  }

  return (
    <details className={cardClass(gate, working)}>
      <summary className="gate-summary">
        <GateHeading gate={gate} working={false} />
      </summary>

      <div className="gate-content">
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
      </div>
    </details>
  );
}

function GateHeading({ gate, working }: { gate: GateResult; working: boolean }): React.JSX.Element {
  return (
    <span className="gate-head">
      <span className="gate-mark" aria-hidden="true">
        {working ? <Spinner /> : gate.passed ? "✓" : "✕"}
      </span>
      <span className="gate-name">{humanise(gate.gate)}</span>
      <span className="gate-state">{stateWord(gate, working)}</span>
    </span>
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
