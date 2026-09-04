/**
 * Turning the values the service sends into the words that appear on screen.
 *
 * Everything here is presentation and nothing here is judgement. No function in this
 * file decides anything about a claim: they put labels on values that have already been
 * decided, and they do it the same way every time.
 *
 * **Nothing here does arithmetic on money.** The one money function pads a figure out
 * for display and never adds, multiplies or rounds. Working out what a claim is worth
 * belongs to the service, which does it exactly; a browser cannot.
 */
import type { GateName, TerminalReason } from "./api/types";

/** The four checks, in words a rep would use rather than the service's own names. */
const GATE_LABELS: Record<GateName, string> = {
  age: "Age of the claim",
  claim_type: "Kind of claim",
  key_information: "Key information",
  insurance: "Insurance",
};

/** What each check is actually asking, for someone meeting them for the first time. */
const GATE_QUESTIONS: Record<GateName, string> = {
  age: "Was the claim filed soon enough after the parcel was delivered?",
  claim_type: "Is this a damaged-in-transit claim, the only kind handled here?",
  key_information: "Are the parcel, the order and the merchant's description all there?",
  insurance: "Was the parcel uninsured? An insured one follows a different process.",
};

/** Why a claim was stopped, in one short phrase. */
const REASON_LABELS: Record<TerminalReason, string> = {
  shipment_insured: "The parcel was insured",
  claim_too_old: "Filed too long after delivery",
  wrong_claim_type: "Not a damaged-in-transit claim",
  missing_key_information: "Key information is missing",
};

/** The name of one of the four checks. */
export function gateLabel(gate: GateName): string {
  return GATE_LABELS[gate];
}

/** The question one of the four checks is asking. */
export function gateQuestion(gate: GateName): string {
  return GATE_QUESTIONS[gate];
}

/** The short phrase for why a claim was stopped. */
export function reasonLabel(reason: TerminalReason): string {
  return REASON_LABELS[reason];
}

/**
 * Turn a key the service used into a readable label — `days_since_delivery` becomes
 * "Days since delivery".
 *
 * The values a check looked at arrive under the service's own field names. They are
 * shown rather than hidden, because being able to check the working is the point of
 * them, and this is only about making them easier on the eye.
 */
export function humaniseKey(key: string): string {
  const words = key.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * Write a moment in time the same way on every machine — "11 February 2026, 11:36 UTC".
 *
 * The browser's own date formatting changes language and order depending on how the
 * machine is configured, which would mean the same claim reading differently to two
 * people. The service avoids that in the emails it writes for exactly the same reason,
 * and this keeps the screen consistent with it.
 *
 * @param moment - A time as the service sends it, or `null`.
 * @returns The formatted time, or "not recorded" when there is none, or the original
 *   text if it cannot be read as a time — showing what arrived beats inventing a date.
 */
export function formatMoment(moment: string | null): string {
  if (moment === null) {
    return "not recorded";
  }
  const parsed = new Date(moment);
  if (Number.isNaN(parsed.getTime())) {
    return moment;
  }
  const day = parsed.getUTCDate();
  const month = MONTHS[parsed.getUTCMonth()] ?? "";
  const year = parsed.getUTCFullYear();
  const hours = String(parsed.getUTCHours()).padStart(2, "0");
  const minutes = String(parsed.getUTCMinutes()).padStart(2, "0");
  return `${String(day)} ${month} ${String(year)}, ${hours}:${minutes} UTC`;
}

/**
 * Show an amount of money exactly as the service worked it out.
 *
 * The figure arrives as text — `"90.00"` — because it was worked out exactly and a
 * browser number could not hold it that way. It is printed as it stands, with a dollar
 * sign in front. Cents are padded out only when the text is plainly a decimal already,
 * and even that is done on the text: no number is parsed, so no rounding can creep in.
 *
 * @param amount - The figure as text, or `null` when the order could not be read.
 * @returns The amount to print, or "unknown" — which means the order could not be read,
 *   and is deliberately not the same as an order worth nothing.
 */
export function formatMoney(amount: string | null): string {
  if (amount === null) {
    return "unknown";
  }
  const decimal = /^(-?\d+)\.(\d+)$/.exec(amount);
  if (decimal === null) {
    return `$${amount}`;
  }
  const [, whole = "", cents = ""] = decimal;
  return `$${whole}.${cents.padEnd(2, "0")}`;
}

/**
 * How long the merchant took to file, in words.
 *
 * @param days - Days from delivery to the claim being filed, or `null` when no delivery
 *   date is known anywhere.
 */
export function formatDayCount(days: number | null): string {
  if (days === null) {
    return "unknown";
  }
  return days === 1 ? "1 day" : `${String(days)} days`;
}
