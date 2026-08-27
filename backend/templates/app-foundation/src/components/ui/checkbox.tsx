"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Check } from "lucide-react";

interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => {
    const inputId = id || React.useId();
    return (
      <div className="flex items-center gap-2">
        <div className="relative">
          <input
            type="checkbox"
            ref={ref}
            id={inputId}
            className={cn("peer h-4 w-4 shrink-0 rounded border border-primary shadow focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 appearance-none checked:bg-primary", className)}
            {...props}
          />
          <Check className="absolute top-0 left-0 h-4 w-4 text-primary-foreground pointer-events-none opacity-0 peer-checked:opacity-100" />
        </div>
        {label && <label htmlFor={inputId} className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">{label}</label>}
      </div>
    );
  }
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
