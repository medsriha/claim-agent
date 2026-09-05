/**
 * Which kinds of claim come back ready to send, and which need a person.
 *
 * Four cuts of the same claims, each showing the share that went out exactly as produced. Three
 * of them are things known before anybody looks at the claim — what the merchant said was
 * damaged, what they said caused it, and who carried the parcel — and the fourth is how sure the
 * system said it was.
 *
 * The point is not any single number but the **spread inside a group**, which is why the service
 * writes that spread out and orders the groups by it. A group near the top sorts the work before
 * anybody starts on it; one near the bottom says that way of sorting claims does not help, which
 * is a finding rather than a gap.
 *
 * Every label is printed as the service wrote it. Most are ShipBob's own words for a real thing —
 * a carrier, a kind of damage — and the confidence bands are named by the range they cover, so
 * there is nothing here to reshape and nothing to look up.
 *
 * Drawn with plain bars rather than a chart, because there is one measure across a handful of
 * named groups and a row of labelled bars reads faster than a plot would. The bar's length comes
 * from a value the service worked out; the browser hands it to CSS and does no arithmetic — the
 * `calc` is the stylesheet's, not this file's.
 */
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
