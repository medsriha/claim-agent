/**
 * One claim threshold on the policy panel: what it is called, what it means, and the
 * control that changes it.
 *
 * Which control appears is decided by the `kind` the service sent, never by the name of
 * the value or by anything this screen knows about claims. Add a threshold to the policy
 * and it turns up here with the right control and the service's own explanation under it.
 *
 * Nothing here judges a value. What is typed is sent as typed, and the service is the only
 * thing that decides whether a value is allowed — including whether it is a number at all,
 * which is why every box is an ordinary text box rather than a number box that would round
 * or reject on its own.
 */
import { humanise } from "../display";
import type { PolicyValue } from "../api/policyTypes";
import type { ValueProblem } from "../api/failure";

interface PolicyValueRowProps {
  /** The value as the panel currently holds it, including anything typed into it. */
  value: PolicyValue;
  /** The service's complaints about this value, if it refused a change to it. */
  problems: readonly ValueProblem[];
  /** True while a request is in flight, so the controls can be held still. */
  busy: boolean;
  /** Called with the whole value, edited. Never called with a different kind. */
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
        {/* The service's own flag: this is what is in force, and it is no longer what the
            service started with. A box that has been typed into but not saved is not
            marked here — the save button is what says that. */}
        {value.changed && <span className="policy-value-changed">Changed</span>}
      </div>

      <p className="policy-value-description">{value.description}</p>

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

      {/* Picked, not typed. The service says which values work this way and supplies the
          choices, so the panel never holds a list of claim types of its own. */}
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
