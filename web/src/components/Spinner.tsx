/**
 * Something turning, to say a step is being worked on.
 *
 * Hidden from anything reading the page aloud: the message it sits in already says what is
 * happening in words, and a turning ring adds nothing to hear.
 */
export function Spinner(): React.JSX.Element {
  return <span className="spinner" aria-hidden="true" />;
}
