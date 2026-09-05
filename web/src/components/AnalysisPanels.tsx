/**
 * The pieces of the analysis screen that are not charts.
 *
 * The period it covers, the one big figure, the tiles, the savings, and the small branch that
 * decides whether a panel has anything to show.
 *
 * Every sentence on any of them was written by the service that worked the figures out. These
 * components add labels and nothing that could be mistaken for a finding.
 */
import type { Figure, Panel } from "../api/analysisTypes";

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

/**
 * Which stretch of time everything below covers.
 *
 * A line rather than a row of buttons. There was a choice of three periods once; it went when the
 * screen stopped asking a service for them, because offering a choice means carrying a set of
 * figures for each and three sets nobody switches between is weight in the page for nothing. The
 * sentence stays, because a dashboard that does not say what it covers is not saying much.
 */
export function PeriodLine({ label }: { label: string }): React.JSX.Element {
  return <p className="analysis-period">{label}</p>;
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

/** What the time saved is worth. */
export function SavingsPanel({ savings }: { savings: readonly Figure[] }): React.JSX.Element {
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
    </section>
  );
}
