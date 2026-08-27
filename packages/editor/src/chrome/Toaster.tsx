import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type Toast = { id: string; title: string; kind?: "info" | "error" };
type ToastContextValue = { push: (t: Omit<Toast, "id">) => void };

const ToastCtx = createContext<ToastContextValue>({ push: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, ...t }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 5000);
  }, []);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div
        style={{
          position: "fixed",
          bottom: 16,
          right: 16,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          zIndex: 4000,
        }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            style={{
              padding: "8px 12px",
              borderRadius: 6,
              background: t.kind === "error" ? "#fee2e2" : "#dbeafe",
              color: t.kind === "error" ? "#7f1d1d" : "#1e3a8a",
              fontSize: 13,
              boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
              minWidth: 200,
            }}
          >
            {t.title}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastContextValue {
  return useContext(ToastCtx);
}
