/**
 * One of the four eligibility checks: what it decided, and the values it looked at.
 *
 * Each check is reported on its own, and all four are always reported, whether they passed
 * or failed. Showing the ones that passed matters as much as the one that failed — a
 * representative can see the insurance check ran and cleared rather than inferring it from
 * silence. Each card opens to reveal what the check read, so a finding can be checked
 * rather than merely trusted.
 */
import { humanise } from "../display";
import type { GateResult } from "../api/types";

export function GateCard({ gate }: { gate: GateResult }): React.JSX.Element {
  const observed = Object.entries(gate.observed);

  return (
    <div className={gate.passed ? "gate gate-passed" : "gate gate-failed"}>
      <div className="gate-head">
        <span className="gate-mark" aria-hidden="true">
          {gate.passed ? "✓" : "✕"}
        </span>
        <h4 className="gate-name">{humanise(gate.gate)}</h4>
        <span className="gate-state">{gate.passed ? "Passed" : "Failed"}</span>
      </div>

      <p className="gate-explanation">{gate.explanation}</p>

      {observed.length > 0 && (
        <details className="observed">
          <summary className="observed-summary">What it looked at</summary>
          <dl className="observed-list">
            {observed.map(([key, value]) => (
              <div key={key} className="observed-row">
                <dt className="observed-key">{humanise(key)}</dt>
                {/* An empty value is a real answer here — "nothing was missing" — so it is
                    drawn rather than left as blank space that reads like a bug. */}
                <dd className="observed-value">{value === "" ? "—" : value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
