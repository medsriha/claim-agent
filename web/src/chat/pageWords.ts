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
 * stage did not exist went away, because the stage does. It grew by one when a report could
 * be sent back and reworked, because the service says the conversation is waiting on a
 * person with a flag rather than with words, and by one more when a message could cause the
 * whole claim to be investigated again.
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

  /**
   * Shown under a round of the conversation where the agent asked the representative
   * something (FR-R.10).
   *
   * The service sends a flag saying its reply contains a question, not a sentence saying
   * the conversation is waiting. The question itself is the agent's own words and is shown
   * as they wrote it; this only says what the flag means, because a flag cannot be read.
   */
  waitingOnYou: "Waiting on your answer to that question.",

  /**
   * Shown under a round where the agent had the whole claim investigated again (FR-1a.4).
   *
   * The service records that as a flag on the round, not as a sentence. The agent's own reply
   * usually says it too, in its own words, but the flag is the fact — and a representative
   * needs to know that new reports exist further down the claim.
   */
  investigatedAgain:
    "The claim was investigated again, so this claim now has a report for each damaged product.",
} as const;
