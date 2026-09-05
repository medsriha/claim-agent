/**
 * The shapes the claims service uses for the claim policy — the numbers every claim is
 * judged by.
 *
 * Every name matches a field the service actually sends, with nothing renamed on the way
 * in, so this can be read side by side with the Python models and checked against them.
 *
 * **Numbers arrive as text, and go back as text.** An amount of money must never become
 * a browser number — a $100.00 cap that comes back as 100.00000000000001 is the failure
 * this project most wants to avoid — and whole numbers travel the same way so the panel
 * has one rule rather than two. Nothing in the screen reads a number out of any of them.
 */

/**
 * What every policy value carries, whatever its kind.
 *
 * `name` is the value's name in the service, and what the panel sends back when it
 * changes. `description` is the service's own sentence explaining what the value is for —
 * several of them say the value is provisional and awaiting ShipBob's sign-off, which is
 * worth reading. `changed` is true when the value in force is no longer the one the
 * service started with.
 */
interface PolicyValueCommon {
  name: string;
  description: string;
  changed: boolean;
}

/** A value typed into a box: a whole number, an amount of money, a fraction, or words. */
export interface PolicyValueWritten extends PolicyValueCommon {
  kind: "integer" | "money" | "fraction" | "text";
  value: string;
  startup_value: string;
}

/**
 * A value picked from a list rather than typed.
 *
 * `options` are the choices the service offers, in its order, and the panel offers
 * exactly those. It is what the panel suggests rather than what the service will accept:
 * the value behind it is ordinary text, so a claim type set from the environment that is
 * not in the list is still valid — and the service includes whatever is currently in
 * force in `options` for exactly that reason, so the control can always show it.
 */
export interface PolicyValueChoice extends PolicyValueCommon {
  kind: "choice";
  value: string;
  startup_value: string;
  options: string[];
}

/** A value that is either yes or no. */
export interface PolicyValueYesNo extends PolicyValueCommon {
  kind: "boolean";
  value: boolean;
  startup_value: boolean;
}

/**
 * One policy value.
 *
 * `kind` says which of the three shapes it is, so the panel picks a control by looking at
 * that one field rather than guessing from what is present. The service sends six kinds
 * across the three shapes: `integer`, `money`, `fraction` and `text` are typed into a
 * box, `choice` is picked from a list, and `boolean` is a yes-or-no.
 */
export type PolicyValue = PolicyValueWritten | PolicyValueChoice | PolicyValueYesNo;

/**
 * The whole claim policy as the panel sees it.
 *
 * `values` are in the order the service declares them, and are never re-ordered on
 * screen. `changed_at` is when the values in force last genuinely changed, and is `null`
 * when they are still the ones the service started with — which is also what
 * `matches_startup` says, and what decides whether there is anything to put back.
 */
export interface PolicyView {
  values: PolicyValue[];
  changed_at: string | null;
  matches_startup: boolean;
}

/** One value as the panel submits it, in the same two shapes the service sends. */
type SubmittedValue = string | boolean;

/** What the panel submits: a value per name. */
export type SubmittedValues = Record<string, SubmittedValue>;

/**
 * How many merchant corrections an operator has just thrown away.
 *
 * A count rather than nothing, because "it worked" and "there was nothing there" look
 * identical on a screen otherwise.
 */
export interface ForgottenCorrections {
  readonly forgotten: number;
}
