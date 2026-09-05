/**
 * The pieces of the analysis screen that are not charts.
 *
 * The filter row, the one big figure, the tiles, the savings and what they rest on, the table of
 * candidate rules, and the small branch that decides whether a panel has anything to show.
 *
 * Every sentence on any of them came from the service. These components add labels — "Period",
 * a column heading — and nothing that could be mistaken for a finding.
 */
import { humanise } from "../display";
import { Spinner } from "./Spinner";
import type { Assumption, Figure, GateTable, Panel, Preset } from "../api/analysisTypes";

/**
 * Show a panel's contents, or the service's own sentence saying why there are none.
 *
 * The distinction this keeps is the one the whole screen rests on. "Nothing was decided in this
 * period" is an ordinary answer about a quiet month. "The store could not be read" is an outage,
 * and it never reaches here — it fails the whole request instead. So an empty panel always means
 * the first, and it says which in the service's words rather than showing an empty box that
 * reads as a screen that broke.
 */
export function PanelState<Drawn>({
  panel,
  children,
}: {
  panel: Panel<Drawn>;
  children: (data: Drawn) => React.JSX.Element;
}): React.JSX.Element {
  if (panel.data === null) {
    return (
      <section className="panel">
        <p className="empty">{panel.empty_reason}</p>
      </section>
    );
  }
  return children(panel.data);
}

interface FilterRowProps {
  presets: readonly Preset[];
  periodLabel: string;
  busy: boolean;
  onPick: (key: string) => void;
}

/**
 * The one row of controls, scoping everything below it.
 *
 * The choices are the service's, and what goes back is the key it sent. The screen never works
 * out a date: two people asking for "12 months" get the same window because the service decided
 * where it starts, not the browser.
 */
export function FilterRow({
  presets,
  periodLabel,
  busy,
  onPick,
}: FilterRowProps): React.JSX.Element {
  return (
    <section className="analysis-filters">
      <div className="filter-group">
        <span className="filter-label">Period</span>
        {presets.map((preset) => (
          <button
            className={preset.applied ? "chip chip-picked" : "chip"}
            type="button"
            key={preset.key}
            disabled={busy}
            aria-pressed={preset.applied}
            onClick={() => {
              onPick(preset.key);
            }}
          >
            {preset.label}
          </button>
        ))}
        {busy && <Spinner />}
      </div>
      <p className="filter-period">{periodLabel}</p>
    </section>
  );
}

/** The one figure the screen leads on. */
export function HeroFigure({ hero }: { hero: Figure }): React.JSX.Element {
  return (
    <section className="panel hero">
      <h2 className="hero-label">{hero.label}</h2>
      <p className="hero-figure">{hero.value}</p>
      {hero.note !== null && <p className="hero-note">{hero.note}</p>}
    </section>
  );
}

/**
 * The tiles, drawn in whatever order the service sent them.
 *
 * The screen does not know what is in this list, so another figure can be added to the service
 * and appear here without anything being changed — the same arrangement that lets a new
 * threshold appear on the rules screen.
 */
export function FigureTiles({
  title,
  figures,
}: {
  title: string | null;
  figures: readonly Figure[];
}): React.JSX.Element {
  return (
    <section className="panel">
      {title !== null && <h3 className="panel-title">{title}</h3>}
      <div className="facts">
        {figures.map((figure) => (
          <div className="fact" key={figure.label}>
            <span className="fact-label">{figure.label}</span>
            <span className="fact-value">{figure.value}</span>
            {figure.note !== null && <span className="fact-note">{figure.note}</span>}
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * What the time saved is worth, and the numbers that figure rests on.
 *
 * The assumptions are shown rather than hidden, with the service's own explanation and its own
 * mark saying they are provisional. A saving in dollars is a measurement multiplied by an hourly
 * rate somebody chose, and a reader who cannot see the rate has no way to argue with the total.
 */
export function SavingsPanel({
  savings,
  assumptions,
}: {
  savings: readonly Figure[];
  assumptions: readonly Assumption[];
}): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">What that is worth</h3>
      <div className="facts">
        {savings.map((figure) => (
          <div className="fact" key={figure.label}>
            <span className="fact-label">{figure.label}</span>
            <span className="fact-value">{figure.value}</span>
            {figure.note !== null && <span className="fact-note">{figure.note}</span>}
          </div>
        ))}
      </div>

      <h4 className="subhead">What those figures assume</h4>
      <ul className="assumptions">
        {assumptions.map((assumption) => (
          <li className="assumption" key={assumption.label}>
            <span className="assumption-head">
              <span className="assumption-label">{assumption.label}</span>
              <span className="assumption-value">{assumption.value}</span>
              <span className="assumption-marker">{assumption.marker}</span>
            </span>
            <span className="assumption-why">{assumption.description}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The candidate rules, as a table and nothing else.
 *
 * There is no button, no switch and no colour on the verdict, and the rows are drawn in the order
 * the service scored them rather than sorted. All three are deliberate. Sorting by coverage would
 * be the screen ranking automation candidates, and a green "meets bar" would read as a
 * recommendation — when the requirements say a person approving is the only way a claim is ever
 * released. The caveat travels with the table so one cannot be shown without the other.
 */
export function AutomationGates({ gates }: { gates: GateTable }): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">{gates.title}</h3>
      <div className="table-scroll">
        <table className="lines">
          <thead>
            <tr>
              {gates.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {gates.rows.map((row) => (
              <tr key={`${row.value_band}-${row.confidence_band}`}>
                <td>{humanise(row.value_band)}</td>
                <td>{humanise(row.confidence_band)}</td>
                <td className="numeric">{row.decisions_text}</td>
                <td className="numeric">{row.coverage_text}</td>
                <td className="numeric">{row.agreement_text}</td>
                <td className="gates-verdict">{humanise(row.verdict)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="gates-caveat">{gates.caveat}</p>
    </section>
  );
}
