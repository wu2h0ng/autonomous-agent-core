import React from "react";
import { createRoot } from "react-dom/client";

function App(): React.JSX.Element {
  return (
    <main style={{ padding: 16, fontFamily: "system-ui" }}>
      <h1>Agent OS</h1>
      <p>Workspace Canvas (Wave 2a)</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
