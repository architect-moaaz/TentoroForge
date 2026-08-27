"use client";
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-[#1E40AF] text-white hover:bg-[#1E40AF]/90",
        secondary:
          "border-transparent bg-[#7C3AED] text-white hover:bg-[#7C3AED]/90",
        destructive:
          "border-transparent bg-[#DC2626] text-white hover:bg-[#DC2626]/90",
        outline: "text-foreground border border-input bg-background hover:bg-accent",
        success:
          "border-transparent bg-[#059669] text-white hover:bg-[#059669]/90",
        warning:
          "border-transparent bg-[#D97706] text-white hover:bg-[#D97706]/90",
        muted:
          "border-transparent bg-muted text-muted-foreground hover:bg-muted/80",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };