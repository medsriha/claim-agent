/**
 * Every sentence on the screen that the system did not write.
 *
 * The rule this project works to is that almost everything a representative reads should
 * have come from the service, and that the screen adds labels rather than commentary. The
 * sentences below break that rule because the service has no way to say them for itself,
 * and they live here so a reader can check the whole list in one place rather than hunting
 * for invented wording across the components.
 *
 * The list got shorter when the investigation was built: the sentence explaining that the
 * stage did not exist went away, because the stage does.
 *
 * Before adding to it, be sure the service really cannot say the thing instead.
 */

export const PAGE_WORDS = {
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
