/** The page: a ShipBob header, and whichever of the two screens is chosen. */
import { useState } from "react";

import { PolicyScreen } from "./screens/PolicyScreen";
import { PreflightScreen } from "./screens/PreflightScreen";
import { ShipBobLogo } from "./theme/ShipBobLogo";

/**
 * The two screens this demo has.
 *
 * `screening` is the representative's job: pick a claim, see what the checks decided.
 * `policy` is the admin's: change the numbers those checks judge by.
 */
type Screen = "screening" | "policy";

export function App(): React.JSX.Element {
  const [showing, setShowing] = useState<Screen>("screening");

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <ShipBobLogo />
          <h1 className="header-title">Claims pre-flight</h1>
          <nav className="header-nav" aria-label="Screens">
            <ScreenTab screen="screening" label="Screening" showing={showing} onChoose={setShowing} />
            <ScreenTab screen="policy" label="Admin panel" showing={showing} onChoose={setShowing} />
          </nav>
        </div>
      </header>

      {/* The screen that is not showing is taken down rather than hidden. Coming back to a
          conversation that was screened under the old policy, sitting beside a policy that
          has since changed, would be the one thing on this page that could mislead. */}
      {showing === "screening" ? <PreflightScreen /> : <PolicyScreen />}
    </div>
  );
}

interface ScreenTabProps {
  screen: Screen;
  label: string;
  showing: Screen;
  onChoose: (screen: Screen) => void;
}

/** One tab in the header. Marked as the current page for anything reading the page aloud. */
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
