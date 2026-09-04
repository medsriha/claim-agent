/**
 * The bar at the top where a rep types the claim they want screened.
 *
 * It also offers the sample claim ids as buttons, so someone opening this for the first
 * time can try it without knowing an id. The buttons are labelled with the ids and
 * nothing else on purpose: saying what each one demonstrates would mean this screen
 * asserting an outcome it does not decide, and the moment a threshold changed, the label
 * would be a lie.
 */
import { useState } from "react";

/** The claims the ShipBob stand-in serves. Ids only — the screening says what they are. */
const SAMPLE_CASE_IDS = [
  "CASE-1001",
  "CASE-1002",
  "CASE-1003",
  "CASE-1004",
  "CASE-1005",
  "CASE-9001",
  "CASE-9002",
  "CASE-9003",
  "CASE-9004",
];

interface CaseLookupProps {
  /** Called with the id to screen. Never called with blank or untrimmed text. */
  onScreen: (caseId: string) => void;
  /** True while a screening is running, so the controls can be held still. */
  busy: boolean;
}

export function CaseLookup({ onScreen, busy }: CaseLookupProps): React.JSX.Element {
  const [caseId, setCaseId] = useState("");

  const chooseSample = (sampleId: string): void => {
    setCaseId(sampleId);
    onScreen(sampleId);
  };

  return (
    <section className="lookup" aria-label="Screen a claim">
      <form
        className="lookup-form"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = caseId.trim();
          if (trimmed !== "") {
            onScreen(trimmed);
          }
        }}
      >
        <label className="lookup-label" htmlFor="case-id">
          Case id
        </label>
        <input
          id="case-id"
          className="lookup-input"
          type="text"
          value={caseId}
          placeholder="CASE-1001"
          autoComplete="off"
          spellCheck={false}
          disabled={busy}
          onChange={(event) => {
            setCaseId(event.target.value);
          }}
        />
        <button className="button-primary" type="submit" disabled={busy || caseId.trim() === ""}>
          {busy ? "Screening…" : "Screen claim"}
        </button>
      </form>

      <div className="samples">
        <span className="samples-label">Sample claims</span>
        <div className="samples-list">
          {SAMPLE_CASE_IDS.map((sampleId) => (
            <button
              key={sampleId}
              className="chip"
              type="button"
              disabled={busy}
              onClick={() => {
                chooseSample(sampleId);
              }}
            >
              {sampleId}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
