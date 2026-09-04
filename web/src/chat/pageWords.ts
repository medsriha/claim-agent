/**
 * Every sentence on the screen that the system did not write.
 *
 * The rule this project works to is that almost everything a representative reads should
 * have come from the service, and that the screen adds labels rather than commentary. The
 * sentence below breaks that rule because the service has no way to say it for itself, and
 * it lives here so a reader can check the whole list in one place rather than hunting for
 * invented wording across the components.
 *
 * Before adding to it, be sure the service really cannot say the thing instead.
 */

export const PAGE_WORDS = {
  /**
   * Shown after a claim clears all four checks.
   *
   * A claim that passes has no drafted email — the service only writes one to explain a
   * stop — so without this the conversation would end on four green checks and silence,
   * which reads as a page that broke rather than a stage that does not exist.
   */
  investigationNotBuilt:
    "The stage that investigates a claim has not been built yet, so there is no email " +
    "for this one and nothing to send.",
} as const;
