import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ControlCenter from "./ControlCenter";

const view = new URLSearchParams(window.location.search).get("view");
const RootView = view === "control" ? ControlCenter : App;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RootView />
  </React.StrictMode>
);
