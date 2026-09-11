import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";

interface ToastItem {
  id: number;
  message: string;
  tone: "success" | "info" | "error";
}

interface ToastContextValue {
  toast: (message: string, tone?: ToastItem["tone"]) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => undefined });

export function useToast() {
  return useContext(ToastContext);
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, tone: ToastItem["tone"] = "info") => {
    const id = nextId++;
    setItems((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3600);
  }, []);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        style={{
          position: "fixed",
          right: 20,
          bottom: 72,
          zIndex: 200,
          display: "grid",
          gap: 8,
          pointerEvents: "none",
        }}
      >
        <AnimatePresence>
          {items.map((item) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="glass-strong"
              style={{
                borderRadius: "var(--radius-control)",
                padding: "10px 16px",
                fontSize: 13,
                color:
                  item.tone === "success"
                    ? "var(--success)"
                    : item.tone === "error"
                      ? "var(--danger)"
                      : "var(--text)",
                pointerEvents: "auto",
                maxWidth: 360,
              }}
            >
              {item.message}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
