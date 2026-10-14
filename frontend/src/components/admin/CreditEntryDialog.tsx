"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { CreditKind } from "@/lib/admin-types";

const KINDS: { value: CreditKind; label: string; sign: "+" | "-" | "±" }[] = [
  { value: "opening", label: "Opening balance", sign: "+" },
  { value: "top_up", label: "Top-up", sign: "+" },
  { value: "adjustment", label: "Adjustment", sign: "±" },
  { value: "refund", label: "Refund", sign: "-" },
];

/**
 * Whether an entry may be recorded: an amount with the sign its kind
 * demands (a top-up or opening balance positive, a refund negative, an
 * adjustment either way but not nothing) and a reason of a few characters,
 * because every entry is read back later by someone who was not there.
 */
export function entryReady(kind: CreditKind, amount: string, note: string): boolean {
  const value = Number(amount);
  if (amount.trim() === "" || !Number.isFinite(value)) return false;
  const signOk = kind === "refund" ? value < 0 : kind === "adjustment" ? value !== 0 : value > 0;
  return signOk && note.trim().length >= 3;
}

/** A signed entry with a reason: a top-up is positive, a refund negative, an adjustment either way. */
export function CreditEntryDialog({
  open, onOpenChange, orgName, hasOpening, pending, onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgName: string;
  hasOpening: boolean;
  pending?: boolean;
  onSubmit: (body: { amount_usd: number; kind: CreditKind; note: string }) => void;
}) {
  const [kind, setKind] = useState<CreditKind>(hasOpening ? "top_up" : "opening");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (open) { setKind(hasOpening ? "top_up" : "opening"); setAmount(""); setNote(""); }
  }, [open, hasOpening]);

  const value = Number(amount);
  const ready = entryReady(kind, amount, note);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Credit entry for {orgName}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="space-y-1.5">
            <Label>Kind</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as CreditKind)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {KINDS.filter((k) => k.value !== "opening" || !hasOpening).map((k) => (
                  <SelectItem key={k.value} value={k.value}>{k.label} ({k.sign})</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="amount">Amount (USD{kind === "refund" ? ", negative" : kind === "adjustment" ? ", signed" : ""})</Label>
            <Input id="amount" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
                   placeholder={kind === "refund" ? "-25" : "100"} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="note">Reason</Label>
            <Textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="Invoice, top-up, correction… written to the record" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!ready || pending} onClick={() => onSubmit({ amount_usd: value, kind, note: note.trim() })}>
            Record entry
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
