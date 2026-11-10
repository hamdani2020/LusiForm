import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { AuthClient } from "./auth/client";
import { loadAuthConfig } from "./auth/config";
import "./index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found");
}

const config = loadAuthConfig();

createRoot(root).render(
  <StrictMode>
    <App client={config ? new AuthClient(config) : null} />
  </StrictMode>,
);
