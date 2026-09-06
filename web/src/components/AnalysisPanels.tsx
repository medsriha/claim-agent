import type { Figure, Panel } from "../api/analysisTypes";

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

export function PeriodLine({ label }: { label: string }): React.JSX.Element {
  return <p className="analysis-period">{label}</p>;
}

export function HeroFigure({ hero }: { hero: Figure }): React.JSX.Element {
  return (
    <section className="panel hero">
      <h2 className="hero-label">{hero.label}</h2>
      <p className="hero-figure">{hero.value}</p>
    </section>
  );
}

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
          </div>
        ))}
      </div>
    </section>
  );
}

export function SavingsPanel({ savings }: { savings: readonly Figure[] }): React.JSX.Element {
  return (
    <section className="panel">
      <h3 className="panel-title">Estimated time and cost savings</h3>
      <div className="facts">
        {savings.map((figure) => (
          <div className="fact" key={figure.label}>
            <span className="fact-label">{figure.label}</span>
            <span className="fact-value">{figure.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
