import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// Native context menus only where the app provides them.
window.addEventListener("contextmenu", (e) => {
  if (!(e.target as HTMLElement).closest("input, textarea")) e.preventDefault();
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
