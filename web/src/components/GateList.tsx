/**
 * The four eligibility checks, all of them, whether they passed or failed.
 *
 * Showing the ones that passed matters as much as the one that failed: a rep can see the
 * insurance check ran and cleared rather than inferring it from silence. Each can be
 * opened to reveal the values it looked at, so a finding can be checked, not just trusted.
 */
import { gateLabel, humaniseKey } from "../display";
import type { GateResult } from "../api/types";

interface GateListProps {
  gates: GateResult[];
}

export function GateList({ gates }: GateListProps): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">The four checks</h3>
      <ul className="gate-list">
        {gates.map((gate) => (
          <GateCard key={gate.gate} gate={gate} />
        ))}
      </ul>
    </section>
  );
}

function GateCard({ gate }: { gate: GateResult }): React.JSX.Element {
  const observed = Object.entries(gate.observed);

  return (
    <li className={gate.passed ? "gate gate-passed" : "gate gate-failed"}>
      <div className="gate-head">
        <span className="gate-mark" aria-hidden="true">
          {gate.passed ? "✓" : "✕"}
        </span>
        <h4 className="gate-name">{gateLabel(gate.gate)}</h4>
        <span className="gate-state">{gate.passed ? "Passed" : "Failed"}</span>
      </div>

      <p className="gate-explanation">{gate.explanation}</p>

      {observed.length > 0 && (
        <details className="observed">
          <summary className="observed-summary">What it looked at</summary>
          <dl className="observed-list">
            {observed.map(([key, value]) => (
              <div key={key} className="observed-row">
                <dt className="observed-key">{humaniseKey(key)}</dt>
                {/* An empty value is a real answer here — "nothing was missing" — so it is
                    drawn rather than left as blank space that reads like a bug. */}
                <dd className="observed-value">{value === "" ? "—" : value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}
