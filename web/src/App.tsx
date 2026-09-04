/**
 * The page: a ShipBob header, the screening screen, and a footer saying what this is.
 *
 * The footer is not decoration. Anyone can open this and screen any claim — there is no
 * sign-in, no record of who looked, and nothing is kept — and someone seeing it for the
 * first time should not have to guess at that.
 */
import { PreflightScreen } from "./screens/PreflightScreen";
import { ShipBobLogo } from "./theme/ShipBobLogo";

export function App(): React.JSX.Element {
  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <ShipBobLogo />
          <div className="header-titles">
            <h1 className="header-title">Claims pre-flight</h1>
            <p className="header-subtitle">Damaged in transit</p>
          </div>
          <span className="header-tag">Demo</span>
        </div>
      </header>

      <PreflightScreen />

      <footer className="footer">
        <p>
          A demonstration, not a product. It shows the eligibility checks and nothing else,
          because that is all that has been built. It cannot approve anything, send
          anything, or fetch back a screening once the page is closed.
        </p>
        <p>The ShipBob colours and mark here are our own approximation, not ShipBob&rsquo;s.</p>
      </footer>
    </div>
  );
}
