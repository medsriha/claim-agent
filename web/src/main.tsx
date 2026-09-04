/** Starts the page. Finds the one element in the HTML and draws the app into it. */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./theme/shipbob.css";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  // The element is written into index.html, so its absence means the page itself is
  // broken. Failing loudly here beats a blank screen with nothing in the console.
  throw new Error("The page is missing the element the app draws into.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
