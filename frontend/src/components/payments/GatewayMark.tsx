import { BRAND } from "@/lib/payment-gateways";

/** A gateway's mark: its initial on its brand colour. */
export function GatewayMark({ provider, size = 40 }: { provider: string; size?: number }) {
  const b = BRAND[provider] ?? { bg: "#334155", fg: "#FFFFFF", mark: provider.slice(0, 1).toUpperCase() };
  return (
    <span
      aria-hidden
      data-gateway-mark={provider}
      className="grid shrink-0 place-items-center rounded-lg font-bold shadow-sm"
      style={{ width: size, height: size, background: b.bg, color: b.fg, fontSize: Math.round(size * 0.45) }}
    >
      {b.mark}
    </span>
  );
}
