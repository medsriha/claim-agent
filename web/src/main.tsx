import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./theme/shipbob.css";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("The page is missing the element the app draws into.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
