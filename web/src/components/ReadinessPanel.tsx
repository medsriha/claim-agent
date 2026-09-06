import type { Readiness } from "../api/analysisTypes";

export function ReadinessPanel({ readiness }: { readiness: Readiness }): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">{readiness.title}</h3>

      {readiness.groups.map((group) => (
        <div className="readiness-group" key={group.name}>
          <h4 className="subhead">
            {group.name}
            <span className="readiness-spread">{group.spread_text}</span>
          </h4>
          <ul className="readiness-rows">
            {group.rows.map((row) => (
              <li className="readiness-row" key={row.label}>
                <span className="readiness-label">{row.label}</span>
                <span className="readiness-track">
                  {row.ready.value !== null && (
                    <span
                      className="readiness-bar"
                      style={{ width: `calc(${String(row.ready.value)} * 100%)` }}
                    />
                  )}
                </span>
                <span className="readiness-figure">{row.ready.text}</span>
                <span className="readiness-volume">{row.volume.text} decisions reviewed</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

    </section>
  );
}
