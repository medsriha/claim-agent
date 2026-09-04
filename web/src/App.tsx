/** The page: a ShipBob header and the screening screen. */
import { PreflightScreen } from "./screens/PreflightScreen";
import { ShipBobLogo } from "./theme/ShipBobLogo";

export function App(): React.JSX.Element {
  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <ShipBobLogo />
          <h1 className="header-title">Claims pre-flight</h1>
          <span className="header-tag">Demo</span>
        </div>
      </header>
      <PreflightScreen />
    </div>
  );
}
