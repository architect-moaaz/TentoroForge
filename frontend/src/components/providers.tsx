"use client";

// Polyfill crypto.randomUUID for older browsers / in-app webviews.
// It's used in 20+ places in chat.ts and elsewhere; we install it once
// here before any component tree renders so no call site has to guard.
// Runs at MODULE load — before Providers is rendered — so React state
// updates during that first paint have it available too.
if (
  typeof window !== "undefined" &&
  window.crypto &&
  typeof window.crypto.randomUUID !== "function" &&
  typeof window.crypto.getRandomValues === "function"
) {
  (window.crypto as unknown as { randomUUID: () => string }).randomUUID =
    function randomUUID(): string {
      const b = new Uint8Array(16);
      window.crypto.getRandomValues(b);
      // RFC 4122 v4 markers
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useAuthStore } from "@/stores/auth";
import { Toaster } from "@/components/ui/sonner";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function AuthHydrator({ children }: { children: React.ReactNode }) {
  const hydrate = useAuthStore((s) => s.hydrate);
  const hydrated = useRef(false);

  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true;
      hydrate();
    }
  }, [hydrate]);

  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthHydrator>{children}</AuthHydrator>
      <Toaster />
    </QueryClientProvider>
  );
}
