/**
 * Turning values the service sends into words on screen.
 *
 * Presentation only — nothing here decides anything about a claim, and nothing here does
 * arithmetic on money. The money function pads a figure for display and never adds,
 * multiplies or rounds.
 */
import type { GateName, TerminalReason } from "./api/types";

/** The four checks, in words a rep would use rather than the service's own names. */
const GATE_LABELS: Record<GateName, string> = {
  age: "Age of the claim",
  claim_type: "Kind of claim",
  key_information: "Key information",
  insurance: "Insurance",
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

/** The short phrase for why a claim was stopped. */
export function reasonLabel(reason: TerminalReason): string {
  return REASON_LABELS[reason];
}

/** Turn a field name into a label: `days_since_delivery` becomes "Days since delivery". */
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
 * Write a time the same way on every machine — "11 February 2026, 11:36 UTC".
 *
 * The browser's own formatting changes with how the machine is configured, so the same
 * claim would read differently to two people. The service avoids that in the emails it
 * writes for the same reason.
 *
 * @param moment - A time as the service sends it, or `null`.
 * @returns The formatted time, "not recorded" when there is none, or the original text if
 *   it cannot be read as a time — showing what arrived beats inventing a date.
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
 * Show money exactly as the service worked it out.
 *
 * The figure arrives as text and is printed as it stands. Cents are padded only when the
 * text is plainly a decimal already, and that is done on the text — no number is parsed,
 * so no rounding can creep in.
 *
 * @param amount - The figure as text, or `null` when the order could not be read.
 * @returns The amount, or "unknown" — which is not the same as an order worth nothing.
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
 * @param days - Delivery to filing, or `null` when no delivery date is known.
 */
export function formatDayCount(days: number | null): string {
  if (days === null) {
    return "unknown";
  }
  return days === 1 ? "1 day" : `${String(days)} days`;
}
