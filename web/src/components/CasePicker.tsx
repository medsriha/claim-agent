/**
 * The row of claims a representative can screen.
 *
 * There used to be a box to type an id into. It is gone: the stand-in for ShipBob serves
 * only the nine claims listed here, so anything typed could produce nothing but the "no
 * such claim" answer.
 *
 * The buttons carry ids and nothing else on purpose. Saying what each one demonstrates
 * would be the screen asserting an outcome it does not decide.
 */
import { SAMPLE_CASE_IDS } from "../sampleCases";

interface CasePickerProps {
  /** Called with the claim to screen. */
  onPick: (caseId: string) => void;
  /** True while a screening is running, so the buttons can be held still. */
  busy: boolean;
  /** The claim on screen, so the button for it can show as chosen. */
  picked: string | null;
}

export function CasePicker({ onPick, busy, picked }: CasePickerProps): React.JSX.Element {
  return (
    <section className="picker" aria-label="Pick a claim to screen">
      <span className="samples-label">Sample claims</span>
      <div className="samples-list">
        {SAMPLE_CASE_IDS.map((sampleId) => (
          <button
            key={sampleId}
            className={sampleId === picked ? "chip chip-picked" : "chip"}
            type="button"
            disabled={busy}
            aria-current={sampleId === picked}
            onClick={() => {
              onPick(sampleId);
            }}
          >
            {sampleId}
          </button>
        ))}
      </div>
    </section>
  );
}
