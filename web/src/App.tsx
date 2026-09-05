import { useState } from "react";

import { AnalysisScreen } from "./screens/AnalysisScreen";
import { PolicyScreen } from "./screens/PolicyScreen";
import { PreflightScreen } from "./screens/PreflightScreen";
import { ShipBobLogo } from "./theme/ShipBobLogo";

type Screen = "screening" | "policy" | "analysis";

export function App(): React.JSX.Element {
  const [showing, setShowing] = useState<Screen>("screening");

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <ShipBobLogo />
          <h1 className="header-title">Damaged in transit claim platform</h1>
          <nav className="header-nav" aria-label="Screens">
            <ScreenTab screen="screening" label="Screening" showing={showing} onChoose={setShowing} />
            <ScreenTab screen="policy" label="Admin panel" showing={showing} onChoose={setShowing} />
            <ScreenTab screen="analysis" label="Monitoring" showing={showing} onChoose={setShowing} />
          </nav>
        </div>
      </header>

      <Showing screen={showing} />
    </div>
  );
}

function Showing({ screen }: { screen: Screen }): React.JSX.Element {
  switch (screen) {
    case "screening":
      return <PreflightScreen />;
    case "policy":
      return <PolicyScreen />;
    case "analysis":
      return <AnalysisScreen />;
  }
}

interface ScreenTabProps {
  screen: Screen;
  label: string;
  showing: Screen;
  onChoose: (screen: Screen) => void;
}

function ScreenTab({ screen, label, showing, onChoose }: ScreenTabProps): React.JSX.Element {
  const current = screen === showing;
  return (
    <button
      className={current ? "header-tab header-tab-current" : "header-tab"}
      type="button"
      aria-current={current ? "page" : undefined}
      onClick={() => {
        onChoose(screen);
      }}
    >
      {label}
    </button>
  );
}
