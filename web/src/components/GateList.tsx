/**
 * The four eligibility checks, all of them, whether they passed or failed.
 *
 * Showing the checks that passed matters as much as showing the one that failed: a rep
 * can then see that the insurance check ran and cleared, rather than having to infer it
 * from silence. The service sends all four for that reason, and this never filters them.
 *
 * Each check can be opened to reveal the exact values it looked at, so its finding can be
 * checked rather than taken on trust. They are closed to begin with, because the sentence
 * is what a rep reads first and the working is what they turn to when they doubt it.
 */
import { gateLabel, gateQuestion, humaniseKey } from "../display";
import type { GateResult } from "../api/types";

interface GateListProps {
  gates: GateResult[];
}

export function GateList({ gates }: GateListProps): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">The four checks</h3>
      <p className="panel-note">
        Every claim goes through all four. All four are shown, passed or failed.
      </p>
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
        <div className="gate-heading">
          <h4 className="gate-name">{gateLabel(gate.gate)}</h4>
          <span className="gate-state">{gate.passed ? "Passed" : "Stopped the claim"}</span>
        </div>
      </div>

      <p className="gate-question">{gateQuestion(gate.gate)}</p>
      <p className="gate-explanation">{gate.explanation}</p>

      {observed.length > 0 && (
        <details className="observed">
          <summary className="observed-summary">What this check looked at</summary>
          <dl className="observed-list">
            {observed.map(([key, value]) => (
              <div key={key} className="observed-row">
                <dt className="observed-key">{humaniseKey(key)}</dt>
                {/* An empty value is a real answer here — "nothing was missing" — so it is
                    spelled out rather than left as a blank space on the page. */}
                <dd className="observed-value">{value === "" ? "—" : value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}
