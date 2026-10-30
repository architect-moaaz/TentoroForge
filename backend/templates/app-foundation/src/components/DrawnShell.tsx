"use client";
// The design draws no frame of its own: the application draws its own.
import * as React from "react";

export const DRAWN_SHELL = false;

export default function DrawnShell(props: { children?: React.ReactNode; controls?: React.ReactNode; role?: string;
                                           data?: Record<string, Record<string, unknown>> }) {
  return <>{props.children}</>;
}
