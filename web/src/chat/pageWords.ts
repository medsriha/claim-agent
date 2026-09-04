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

  /**
   * Shown when the record of past claims was read and held nothing much like this claim.
   *
   * The service has no sentence for this. It answers with an empty list and a flag saying
   * it managed to look, which is a fact rather than words — so something has to put the
   * fact into a sentence, and an empty box would read as a page that broke.
   */
  noSimilarClaims:
    "No past claim resembles this one closely enough to be worth showing. That is ordinary, " +
    "and it is not the same as this being the first claim of its kind.",

  /**
   * Shown when the past claims could not be looked up at all.
   *
   * The service sends its own sentence whenever it is the store that failed, and that
   * sentence is preferred over this one. This covers the case where the request never got
   * an answer, so there is no sentence from anybody. It must never read as "none found":
   * saying there is no comparable history when nobody looked is the one wrong answer here.
   */
  pastClaimsUnreadable:
    "The past claims could not be looked up, so nothing is known about how similar claims " +
    "were handled. This is not the same as there being none.",
} as const;
