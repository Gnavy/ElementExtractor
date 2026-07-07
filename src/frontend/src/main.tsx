import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Root } from "./Root";
import "element-theme-default";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>
);
