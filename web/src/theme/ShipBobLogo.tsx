/**
 * The mark in the top-left corner of the screen.
 *
 * A STAND-IN, not ShipBob's real logo. It is drawn here rather than loaded as an image
 * so the demo needs no asset file, and so that nobody mistakes it for the genuine mark
 * and ships it somewhere real. Replace it with the actual logo before this is ever put
 * in front of a merchant.
 *
 * It takes its colours from the theme, so it changes with everything else.
 */
export function ShipBobLogo(): React.JSX.Element {
  return (
    <span className="logo">
      <svg
        className="logo-glyph"
        viewBox="0 0 32 32"
        role="img"
        aria-label="ShipBob"
        focusable="false"
      >
        {/* A parcel seen from the front: the box, then the tape down the middle. */}
        <rect x="3" y="8" width="26" height="18" rx="3" fill="currentColor" />
        <path d="M3 13.5h26" stroke="var(--sb-on-brand)" strokeWidth="1.6" opacity="0.55" />
        <path d="M16 8v18" stroke="var(--sb-on-brand)" strokeWidth="1.6" opacity="0.55" />
        {/* The flap, lifted, to keep it from reading as a plain rectangle. */}
        <path
          d="M8 8 11 3h10l3 5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      </svg>
      <span className="logo-word">shipbob</span>
    </span>
  );
}
