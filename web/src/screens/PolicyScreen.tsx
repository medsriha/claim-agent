/**
 * The admin panel: the numbers every claim is judged by, and a way to change them.
 *
 * Almost every threshold in this system is a placeholder somebody invented so the code
 * would run — the service says so itself, in the explanation under each one. This screen
 * exists so a change can be tried and seen: edit the age limit, save, screen a claim, and
 * the claim is judged by the new number with nothing restarted in between.
 *
 * Three things it deliberately does not do. It does not judge a value — what is typed is
 * sent as typed, and the service decides. It does not read a number out of anything, so no
 * amount of money can pass through browser arithmetic. And it does not decide what changed:
 * it sends the whole form and draws whatever the service says is now in force.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiFailure } from "../api/failure";
import { FailureNotice } from "../components/FailureNotice";
import { PolicyValueRow } from "../components/PolicyValueRow";
import { fetchPolicy, forgetCorrections, resetPolicy, savePolicy } from "../api/policyClient";
import { PAGE_WORDS } from "../chat/pageWords";
import { formatMoment } from "../display";
import type { PolicyValue, PolicyView, SubmittedValues } from "../api/policyTypes";
import type { ValueProblem } from "../api/failure";

export function PolicyScreen(): React.JSX.Element {
  const [inForce, setInForce] = useState<PolicyView | null>(null);
  const [draft, setDraft] = useState<PolicyValue[]>([]);
  const [busy, setBusy] = useState(true);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [saved, setSaved] = useState(false);

  /**
   * Send one request and draw its answer.
   *
   * Every one of the three requests answers with the whole policy, so they all end the
   * same way: the panel throws away what it was holding and shows what came back. That is
   * what stops the screen and the service disagreeing about what is in force.
   */
  const send = useCallback((request: () => Promise<PolicyView>, savedOnSuccess: boolean): void => {
    request()
      .then((answer) => {
        setInForce(answer);
        setDraft(answer.values);
        setSaved(savedOnSuccess);
      })
      .catch((error: unknown) => {
        // The client promises to throw only its own failure type. Anything else would be a
        // bug in this screen rather than a problem with the policy, and it still has to end
        // in something readable rather than a blank page.
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

  /** Start a request from a button: say the panel is working, then send it. */
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
    // The panel is built already working, so the first read has nothing to set up front.
    // That matters: an effect that changes state as it runs makes the page draw twice
    // before it has anything to show.
    send(fetchPolicy, false);
  }, [send]);

  const edit = (edited: PolicyValue): void => {
    setSaved(false);
    setDraft((current) =>
      current.map((value) => (value.name === edited.name ? edited : value)),
    );
  };

  // Nothing to save until something is different from what the service holds, and nothing
  // to put back unless the service says the policy has moved off its startup values.
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

      <PastCorrections />
    </main>
  );
}

/**
 * Emptying the store of what representatives have corrected.
 *
 * Sits apart from the policy form because it is not a policy value: the form changes what
 * later claims are judged by, and this throws away what the system has already learned. It is
 * here because both are things an operator does to a service that is already running.
 *
 * It keeps its own state rather than sharing the form's. The two have nothing to do with each
 * other, and a failure to forget must not read as a failure to save.
 */
function PastCorrections(): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [forgotten, setForgotten] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const forget = (): void => {
    setBusy(true);
    setFailure(null);
    setForgotten(null);
    forgetCorrections()
      .then((answer) => {
        setForgotten(answer.forgotten);
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
      <h2 className="panel-title">Past rep corrections</h2>
      <p className="policy-note">{PAGE_WORDS.forgettingCorrections}</p>

      <div className="policy-actions">
        <button className="button-secondary" type="button" disabled={busy} onClick={forget}>
          {busy ? "Working…" : "Forget them all"}
        </button>
      </div>

      {forgotten !== null && (
        <p className="policy-saved" role="status">
          {forgotten === 0 ? "There were none to forget." : `Forgot ${String(forgotten)}.`}
        </p>
      )}
      {failure !== null && (
        <p className="policy-refusal" role="alert">
          {failure}
        </p>
      )}
    </section>
  );
}

/** The complaints the service made about one value, if it refused a change to it. */
function problemsFor(failure: ApiFailure | null, name: string): readonly ValueProblem[] {
  if (failure === null) {
    return [];
  }
  return failure.problems.filter((problem) => problem.name === name);
}

/** The whole form, ready to submit: a value per name, each exactly as it is held. */
function submitted(draft: PolicyValue[]): SubmittedValues {
  const values: SubmittedValues = {};
  for (const value of draft) {
    values[value.name] = value.value;
  }
  return values;
}

/** The value the service sent under this name, if it sent one. */
function servedValue(inForce: PolicyView, name: string): PolicyValue | undefined {
  return inForce.values.find((value) => value.name === name);
}

/** True when a value has been changed away from the one the service sent. */
function differs(value: PolicyValue, served: PolicyValue | undefined): boolean {
  if (served === undefined) {
    return true;
  }
  return value.value !== served.value;
}
