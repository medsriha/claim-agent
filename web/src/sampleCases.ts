/**
 * The claims the ShipBob stand-in serves.
 *
 * Ids only, deliberately. Saying what each one demonstrates would be the screen asserting
 * an outcome it does not decide, and it would become a lie the moment a threshold changed
 * — the age limit is a placeholder, so which of these claims is too old is not fixed.
 *
 * They live in a module of their own rather than inside the picker because the screen
 * needs to name a claim as soon as one is chosen, before any component has rendered it.
 */
export const SAMPLE_CASE_IDS = [
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
