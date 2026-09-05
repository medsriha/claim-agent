/**
 * The write-up a representative acts on when a claim is stopped.
 *
 * The findings are the service's own sentences about why the claim cannot go on. They are
 * printed as they arrive: the screen does not summarise them, reorder them, or add one.
 */
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
