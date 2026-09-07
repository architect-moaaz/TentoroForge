"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CartPanelPropsType } from "./CartPanel.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useDesignTime, useNavigator } from "@tentoroforge/renderer";
import { useMotion } from "../../style/useMotion";

export interface CartPanelProps extends CartPanelPropsType {
  style?: StyleSlotT;
}

type CartRow = {
  id: string;
  itemRef: { entity?: string; id?: string } | null;
  quantity: number;
  priceSnapshot: string | number | null;
  label: string | null;
};
type CartBody = { items: CartRow[]; count: number; subtotal: number };

const DEFAULT_METHODS = ["Cash on delivery", "Invoice / net-30", "Wire transfer"];

function fmt(n: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

export function CartPanel({
  title = "Your cart",
  emptyState = "Your cart is empty.",
  currency = "USD",
  checkoutLabel = "Place order",
  paymentMethods,
  onCheckoutNavigate = "/orders",
  className,
  style,
}: CartPanelProps) {
  const methods = paymentMethods && paymentMethods.length ? paymentMethods : DEFAULT_METHODS;
  // HALF THIS PANEL'S CONFIGURATION SURFACE HAD NO PREVIEW.
  //
  // The checkout footer is inside the non-empty branch, and the editor cannot
  // produce a non-empty cart -- there is no `/api/cart` behind the canvas. So
  // `checkoutLabel`, `paymentMethods` and `onCheckoutNavigate` were three
  // controls whose effect the author could never once see: rename the button to
  // "Buy now" and nothing anywhere changes. The empty state itself is correct
  // and stays; what was missing is the footer next to it.
  //
  // The button is already `disabled` on an empty cart, so showing the footer
  // costs nothing and invents no content -- the labels and the payment list are
  // the author's own values, rendered where they will appear.
  const designTime = useDesignTime();
  const nav = useNavigator();
  const [body, setBody] = React.useState<CartBody | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [method, setMethod] = React.useState<string>(methods[0]);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch("/api/cart", { cache: "no-store" });
      if (!res.ok) {
        setBody({ items: [], count: 0, subtotal: 0 });
        return;
      }
      const data = (await res.json()) as CartBody;
      setBody(data);
    } catch {
      setBody({ items: [], count: 0, subtotal: 0 });
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const handler = () => refresh();
    window.addEventListener("forge-cart-changed", handler);
    return () => window.removeEventListener("forge-cart-changed", handler);
  }, [refresh]);

  const setQty = async (id: string, quantity: number) => {
    setBusy(true);
    try {
      await fetch("/api/cart", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id, quantity }),
      });
      await refresh();
      window.dispatchEvent(new CustomEvent("forge-cart-changed"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      await fetch(`/api/cart?id=${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
      window.dispatchEvent(new CustomEvent("forge-cart-changed"));
    } finally {
      setBusy(false);
    }
  };

  const checkout = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/cart/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ paymentMethod: method }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        setError(String(b?.error || "Checkout failed"));
        return;
      }
      window.dispatchEvent(new CustomEvent("forge-cart-changed"));
      if (onCheckoutNavigate) {
        // WAS `window.location.href = onCheckoutNavigate`, which resolves an
        // app-absolute route against the ORIGIN root -- the same line the
        // base-path fix removed from six other components, missed here. Every
        // schema-driven navigation goes through this seam.
        nav.push(onCheckoutNavigate);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  if (body == null) {
    return <div className={className} data-cart-panel="loading">Loading…</div>;
  }

  const showFooter = body.items.length > 0 || designTime;

  return (
    <div
      data-cart-panel=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      className={["rounded-lg border border-border bg-card p-5 text-card-foreground", className ?? ""].filter(Boolean).join(" ")}
    >
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-lg font-medium">{title}</h2>
        <span className="text-xs text-muted-foreground">{body.count} item{body.count === 1 ? "" : "s"}</span>
      </div>

      {body.items.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">{emptyState}</p>
      )}

      {body.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-start text-xs text-muted-foreground">
                <th className="py-2 font-medium">Item</th>
                <th className="py-2 font-medium">Qty</th>
                <th className="py-2 text-end font-medium">Price</th>
                <th className="py-2 text-end font-medium">Subtotal</th>
                <th className="py-2 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {body.items.map((r) => {
                const price = r.priceSnapshot == null ? 0 : Number(r.priceSnapshot);
                const lineTotal = Math.round(price * (r.quantity || 0) * 100) / 100;
                return (
                  <tr key={r.id} className="border-b border-border last:border-0">
                    <td className="py-3">
                      <span className="font-medium">{r.label || r.itemRef?.entity || "Item"}</span>
                    </td>
                    <td className="py-3">
                      <div className="inline-flex items-center overflow-hidden rounded border border-border">
                        <button type="button" onClick={() => setQty(r.id, Math.max(0, r.quantity - 1))} disabled={busy} className="h-7 w-7 hover:bg-accent">−</button>
                        <span className="w-8 text-center">{r.quantity}</span>
                        <button type="button" onClick={() => setQty(r.id, r.quantity + 1)} disabled={busy} className="h-7 w-7 hover:bg-accent">+</button>
                      </div>
                    </td>
                    <td className="py-3 text-end">{price ? fmt(price, currency) : "—"}</td>
                    <td className="py-3 text-end font-medium">{lineTotal ? fmt(lineTotal, currency) : "—"}</td>
                    <td className="py-3 text-end">
                      <button type="button" onClick={() => remove(r.id)} disabled={busy} aria-label="Remove" className="text-muted-foreground hover:text-destructive">✕</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {showFooter && (
        <div className="mt-5 grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2 sm:items-end">
            <label className="text-xs text-muted-foreground">
              Payment method
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className="mt-1 block h-9 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground"
                disabled={busy}
              >
                {methods.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
            <div className="text-end">
              <div className="text-xs text-muted-foreground">Total</div>
              <div className="text-2xl font-medium">{fmt(body.subtotal, currency)}</div>
              <button
                type="button"
                onClick={checkout}
                disabled={busy || body.items.length === 0}
                className="mt-2 inline-flex h-9 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy ? "Placing…" : checkoutLabel}
              </button>
              {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
            </div>
        </div>
      )}
    </div>
  );
}
