import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider } from "@aiva/ui";
import App from "./App";
import "@aiva/ui/tokens.css";
import "@aiva/ui/fonts.css";
import "./index.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element missing from index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
);
