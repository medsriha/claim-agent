/**
 * Turning values the service sends into words on screen.
 *
 * Presentation only. Nothing here decides anything about a claim, and nothing here
 * invents wording: names the service sends — `claim_too_old`, `key_information` — are
 * reshaped mechanically into readable text, never swapped for a phrase of our own.
 *
 * Nothing here does arithmetic on money either. The money function pads a figure for
 * display and never adds, multiplies or rounds.
 */

/**
 * Turn a name the service sent into readable text: `days_since_delivery` becomes
 * "Days since delivery", `claim_too_old` becomes "Claim too old".
 *
 * Used for field names, check names and stop reasons alike. Doing it mechanically rather
 * than looking each one up in a table of our own wording means the screen can only ever
 * show what the service actually said, and a value we have never seen still reads.
 */
export function humanise(name: string): string {
  const words = name.split("_").join(" ");
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
