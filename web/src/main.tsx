import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./app/App";
import { queryClient } from "./app/queryClient";
import { ShellProvider } from "./app/ShellContext";
import { ToastProvider } from "./components/Toast";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/motion.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ShellProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </ShellProvider>
    </QueryClientProvider>
  </StrictMode>,
);
