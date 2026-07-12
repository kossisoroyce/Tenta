import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Kumo's self-contained stylesheet: design tokens, component styles, the
// utility classes Kumo uses internally, and light/dark theming.
import "@cloudflare/kumo/styles/standalone";
import "./styles.css";

import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
