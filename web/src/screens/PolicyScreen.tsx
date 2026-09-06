import { useCallback, useEffect, useState } from "react";

import { ApiFailure } from "../api/failure";
import { FailureNotice } from "../components/FailureNotice";
import { PolicyValueRow } from "../components/PolicyValueRow";
import { fetchPolicy, forgetEverything, resetPolicy, savePolicy } from "../api/policyClient";
import { formatMoment } from "../display";
import type { ClearedStores, PolicyValue, PolicyView, SubmittedValues } from "../api/policyTypes";
import type { ValueProblem } from "../api/failure";

export function PolicyScreen(): React.JSX.Element {
  const [inForce, setInForce] = useState<PolicyView | null>(null);
  const [draft, setDraft] = useState<PolicyValue[]>([]);
  const [busy, setBusy] = useState(true);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [saved, setSaved] = useState(false);

  const send = useCallback((request: () => Promise<PolicyView>, savedOnSuccess: boolean): void => {
    request()
      .then((answer) => {
        setInForce(answer);
        setDraft(answer.values);
        setSaved(savedOnSuccess);
      })
      .catch((error: unknown) => {

        setFailure(
          error instanceof ApiFailure
            ? error
            : new ApiFailure("unexpected", "This screen ran into a problem of its own."),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }, []);

  const run = useCallback(
    (request: () => Promise<PolicyView>, savedOnSuccess: boolean): void => {
      setBusy(true);
      setFailure(null);
      setSaved(false);
      send(request, savedOnSuccess);
    },
    [send],
  );

  const load = useCallback((): void => {
    run(fetchPolicy, false);
  }, [run]);

  const save = useCallback((): void => {
    run(() => savePolicy(submitted(draft)), true);
  }, [draft, run]);

  const putBack = useCallback((): void => {
    run(resetPolicy, false);
  }, [run]);

  useEffect(() => {

    send(fetchPolicy, false);
  }, [send]);

  const edit = (edited: PolicyValue): void => {
    setSaved(false);
    setDraft((current) =>
      current.map((value) => (value.name === edited.name ? edited : value)),
    );
  };

  const edited =
    inForce !== null && draft.some((value) => differs(value, servedValue(inForce, value.name)));
  const canPutBack = inForce !== null && !inForce.matches_startup;

  if (inForce === null) {
    return (
      <main className="screen">
        {busy && (
          <p className="working" role="status">
            Reading the claim policy…
          </p>
        )}
        {!busy && failure !== null && (
          <FailureNotice kind={failure.kind} message={failure.message} onRetry={load} />
        )}
      </main>
    );
  }

  return (
    <main className="screen">
      <section className="panel">
        <h2 className="panel-title">Claim policy</h2>
        {inForce.changed_at !== null && (
          <p className="policy-force">Last changed {formatMoment(inForce.changed_at)}.</p>
        )}

        <ul className="policy-values">
          {draft.map((value) => (
            <PolicyValueRow
              key={value.name}
              value={value}
              problems={problemsFor(failure, value.name)}
              busy={busy}
              onChange={edit}
            />
          ))}
        </ul>

        {failure !== null && (
          <p className="policy-refusal" role="alert">
            {failure.message}
          </p>
        )}

        {saved && (
          <p className="policy-saved" role="status">
            Saved
          </p>
        )}

        <div className="policy-actions">
          <button
            className="button-primary"
            type="button"
            disabled={busy || !edited}
            onClick={save}
          >
            {busy ? "Working…" : "Save"}
          </button>
          <button
            className="button-secondary"
            type="button"
            disabled={busy || !canPutBack}
            onClick={putBack}
          >
            Reset
          </button>
        </div>
      </section>

      <EverythingRemembered />
    </main>
  );
}

const STORES: readonly (readonly [keyof ClearedStores, string])[] = [
  ["corrections", "Merchant corrections"],
  ["reports", "Reports, every version"],
  ["decisions", "Recorded decisions"],
  ["past_claims", "Past claims"],
];

function EverythingRemembered(): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [cleared, setCleared] = useState<ClearedStores | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const forget = (): void => {
    setBusy(true);
    setFailure(null);
    setCleared(null);
    forgetEverything()
      .then((answer) => {
        setCleared(answer);
      })
      .catch((error: unknown) => {
        setFailure(
          error instanceof ApiFailure
            ? error.message
            : "This screen ran into a problem of its own.",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <section className="panel">
      <h2 className="panel-title">
        Permanently delete all reports, feedback, decisions, corrections, and claim history
      </h2>

      <div className="policy-actions">
        <button className="button-secondary" type="button" disabled={busy} onClick={forget}>
          {busy ? "Working…" : "Forget it all"}
        </button>
      </div>

      {cleared !== null && (
        <div className="policy-saved" role="status">
          {STORES.every(([field]) => cleared[field] === 0) ? (
            <p className="cleared-nothing">There was nothing to forget.</p>
          ) : (
            <ul className="cleared-stores">
              {STORES.map(([field, label]) => (
                <li key={field}>
                  <span>{label}</span>
                  <strong>{String(cleared[field])}</strong>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {failure !== null && (
        <p className="policy-refusal" role="alert">
          {failure}
        </p>
      )}
    </section>
  );
}

function problemsFor(failure: ApiFailure | null, name: string): readonly ValueProblem[] {
  if (failure === null) {
    return [];
  }
  return failure.problems.filter((problem) => problem.name === name);
}

function submitted(draft: PolicyValue[]): SubmittedValues {
  const values: SubmittedValues = {};
  for (const value of draft) {
    values[value.name] = value.value;
  }
  return values;
}

function servedValue(inForce: PolicyView, name: string): PolicyValue | undefined {
  return inForce.values.find((value) => value.name === name);
}

function differs(value: PolicyValue, served: PolicyValue | undefined): boolean {
  if (served === undefined) {
    return true;
  }
  return value.value !== served.value;
}
