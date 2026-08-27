"use client";
import { useState, createContext, useContext, useCallback, type ReactNode } from "react";
import * as RadixToast from "@radix-ui/react-toast";

// ----- Types ---------------------------------------------------------------

type ToastMessage = {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "success" | "danger";
  duration?: number;
};

type ToastContextValue = {
  toast: (msg: Omit<ToastMessage, "id">) => void;
};

// ----- Context -------------------------------------------------------------

const ToastContext = createContext<ToastContextValue | null>(null);

// ----- Provider ------------------------------------------------------------

export function ToastProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ToastMessage[]>([]);

  const toast = useCallback((msg: Omit<ToastMessage, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setMessages((prev) => [...prev, { ...msg, id }]);
  }, []);

  function dismiss(id: string) {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }

  return (
    <ToastContext.Provider value={{ toast }}>
      <RadixToast.Provider swipeDirection="right">
        {children}
        {messages.map((m) => (
          <RadixToast.Root
            key={m.id}
            open
            onOpenChange={(open) => { if (!open) dismiss(m.id); }}
            duration={m.duration ?? 4000}
          >
            <RadixToast.Title>{m.title}</RadixToast.Title>
            {m.description && (
              <RadixToast.Description>{m.description}</RadixToast.Description>
            )}
            <RadixToast.Close aria-label="Close" />
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport
          style={{ position: "fixed", bottom: "1rem", right: "1rem", display: "flex", flexDirection: "column", gap: "0.5rem", zIndex: 9999 }}
        />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}

// ----- Hook ----------------------------------------------------------------

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
