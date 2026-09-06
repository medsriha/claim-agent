import { SAMPLE_CASE_IDS } from "../sampleCases";

interface CasePickerProps {

  onPick: (caseId: string) => void;

  busy: boolean;

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
