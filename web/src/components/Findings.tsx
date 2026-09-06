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
