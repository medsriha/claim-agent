/**
 * The mark in the top-left corner.
 *
 * A stand-in, not ShipBob's real logo — drawn here so the demo needs no asset file.
 * Replace it with the real mark before this goes in front of anyone.
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
