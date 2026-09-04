/**
 * Every sentence on the screen that the system did not write.
 *
 * The rule this project works to is that almost everything a representative reads should
 * have come from the service, and that the screen adds labels rather than commentary. A
 * few sentences have to break that rule because the service has no way to say them for
 * itself, and every one of them is here — so a reader can check the whole list in one
 * place rather than hunting for invented wording across the components.
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
    "That is as far as this demo goes. The stage that investigates a claim has not been " +
    "built, so there is no email for this one and nothing to send.",

  /**
   * Shown after the send button is pressed.
   *
   * The send is a simulation: no address is contacted and there is no address in the
   * service behind the button. A control that looks like it sends is a dangerous thing to
   * leave unexplained, so the screen says outright that nothing left it.
   */
  nothingWasSent:
    "Nothing was sent. This demo has no way to send an email — the merchant was not " +
    "contacted, and the edit above was not recorded anywhere.",

  /**
   * Shown at the top of the policy panel, above the thresholds it can change.
   *
   * A changed threshold lives in the running service and nowhere else, so a restart puts
   * every value back without saying it has. The service cannot tell anyone that about
   * itself, and somebody changing what every later claim is judged by has to know it.
   */
  policyChangesAreNotKept:
    "A change here takes effect on the next claim screened, and is lost when the service " +
    "restarts. Nothing is stored.",
} as const;
