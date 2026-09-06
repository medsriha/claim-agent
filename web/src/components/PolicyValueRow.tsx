import { humanise } from "../display";
import type { PolicyValue } from "../api/policyTypes";
import type { ValueProblem } from "../api/failure";

const INTERNAL_REQUIREMENT_REFERENCES =
  /\s*\((?:N?FR-[A-Za-z0-9.]+)(?:,\s*N?FR-[A-Za-z0-9.]+)*\)/g;

function displayDescription(description: string): string {
  return description
    .replace(INTERNAL_REQUIREMENT_REFERENCES, "")
    .replace(/\s+INVENTED\s+and\s+PROVISIONAL\.?/gi, "")
    .replace(/\s+PROVISIONAL\.?/gi, "")
    .trim();
}

interface PolicyValueRowProps {

  value: PolicyValue;

  problems: readonly ValueProblem[];

  busy: boolean;

  onChange: (value: PolicyValue) => void;
}

export function PolicyValueRow({
  value,
  problems,
  busy,
  onChange,
}: PolicyValueRowProps): React.JSX.Element {
  const controlId = `policy-${value.name}`;

  return (
    <li className={problems.length > 0 ? "policy-value policy-value-refused" : "policy-value"}>
      <div className="policy-value-head">
        <label className="policy-value-name" htmlFor={controlId}>
          {humanise(value.name)}
        </label>

        {value.changed && <span className="policy-value-changed">Changed</span>}
      </div>

      <p className="policy-value-description">{displayDescription(value.description)}</p>

      {value.kind === "boolean" && (
        <label className="policy-toggle" htmlFor={controlId}>
          <input
            id={controlId}
            type="checkbox"
            checked={value.value}
            disabled={busy}
            onChange={(event) => {
              onChange({ ...value, value: event.target.checked });
            }}
          />
          <span>{value.value ? "Yes" : "No"}</span>
        </label>
      )}

      {value.kind === "choice" && (
        <select
          id={controlId}
          className="lookup-input policy-select"
          value={value.value}
          disabled={busy}
          onChange={(event) => {
            onChange({ ...value, value: event.target.value });
          }}
        >
          {value.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      )}

      {value.kind !== "boolean" && value.kind !== "choice" && (
        <input
          id={controlId}
          className="lookup-input policy-input"
          type="text"
          value={value.value}
          autoComplete="off"
          spellCheck={false}
          disabled={busy}
          onChange={(event) => {
            onChange({ ...value, value: event.target.value });
          }}
        />
      )}

      {value.changed && <p className="policy-value-startup">Started as {startupText(value)}</p>}

      {problems.map((problem) => (
        <p key={problem.message} className="policy-value-problem" role="alert">
          {problem.message}
        </p>
      ))}
    </li>
  );
}

/**
 * What this value was when the service started, written the way the control shows it.
 *
 * Only reshaped, never reworded: a yes-or-no reads as yes or no, and everything else
 * exactly as the service sent it.
 */
function startupText(value: PolicyValue): string {
  if (value.kind === "boolean") {
    return value.startup_value ? "Yes" : "No";
  }
  return value.startup_value;
}
