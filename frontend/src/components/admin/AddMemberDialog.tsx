"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function AddMemberDialog({
  open, onOpenChange, orgName, pending, onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgName: string;
  pending?: boolean;
  onSubmit: (email: string, role: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  useEffect(() => { if (open) { setEmail(""); setRole("member"); } }, [open]);
  const ready = /\S+@\S+\.\S+/.test(email);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Add a person to {orgName}</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">An email with an account joins at once; one without is invited.</p>
        <div className="grid gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="member-email">Email</Label>
            <Input id="member-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="member">Member</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
                <SelectItem value="owner">Owner</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!ready || pending} onClick={() => onSubmit(email.trim(), role)}>Add</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
