/**
 * The write-up a representative acts on when a claim is stopped, and when it was screened.
 *
 * The findings are the service's own sentences about why the claim cannot go on. They are
 * printed as they arrive: the screen does not summarise them, reorder them, or add one.
 */
import { formatMoment } from "../display";

/** Why the claim was stopped, one sentence per reason, in the order the service sent them. */
export function Findings({ findings }: { findings: string[] }): React.JSX.Element {
  return (
    <ul className="findings">
      {findings.map((finding) => (
        <li key={finding} className="finding">
          {finding}
        </li>
      ))}
    </ul>
  );
}

/** When the screening ran. Sits with the decision it produced. */
export function EvaluatedAt({ moment }: { moment: string }): React.JSX.Element {
  return <p className="evaluated">Screened {formatMoment(moment)}</p>;
}
