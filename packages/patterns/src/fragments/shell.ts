/**
 * Shell pattern fragments — auth pages, navigation, error pages.
 */

import type { IRNode } from "@tentoroforge/ir";

// ---------------------------------------------------------------------------
// Auth Login
// ---------------------------------------------------------------------------

export function authLoginRoot(appName: string): IRNode {
  return {
    node: "Stack",
    align: "center",
    justify: "center",
    height: "screen",
    padding: "lg",
    children: [
      {
        node: "Stack",
        width: "400px",
        gap: "lg",
        align: "center",
        children: [
          {
            node: "Stack",
            align: "center",
            gap: "sm",
            children: [
              { node: "Text", content: appName, typography: "heading-2" as const, color: "primary" } as IRNode,
              { node: "Text", content: "Welcome back", typography: "heading-1" as const } as IRNode,
              { node: "Text", content: "Sign in to your account", typography: "body-sm" as const } as IRNode,
            ],
          } as IRNode,
          {
            node: "Card",
            padding: "lg",
            children: [
              {
                node: "Form",
                bind: "state:form",
                onSubmit: { type: "mutate" as const, source: "login" },
                layout: "single-column" as any,
                fields: [
                  { field: "email", label: "Email", required: true, node: "TextInput", type: "email", placeholder: "you@company.com" },
                  { field: "password", label: "Password", required: true, node: "TextInput", type: "password", placeholder: "Enter your password" },
                ],
                actions: [
                  {
                    node: "Stack",
                    gap: "md",
                    children: [
                      { node: "Button", label: "Sign In", variant: "primary", width: "full", submit: true } as IRNode,
                    ],
                  } as IRNode,
                ],
              } as IRNode,
            ],
          } as IRNode,
          { node: "Text", content: "Don't have an account? Sign up", typography: "body-sm" as const, align: "center" } as IRNode,
        ],
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Auth Signup
// ---------------------------------------------------------------------------

export function authSignupRoot(appName: string): IRNode {
  return {
    node: "Stack",
    align: "center",
    justify: "center",
    height: "screen",
    padding: "lg",
    children: [
      {
        node: "Stack",
        width: "400px",
        gap: "lg",
        align: "center",
        children: [
          {
            node: "Stack",
            align: "center",
            gap: "sm",
            children: [
              { node: "Text", content: appName, typography: "heading-2" as const, color: "primary" } as IRNode,
              { node: "Text", content: "Create your account", typography: "heading-1" as const } as IRNode,
              { node: "Text", content: `Get started with ${appName}`, typography: "body-sm" as const } as IRNode,
            ],
          } as IRNode,
          {
            node: "Card",
            padding: "lg",
            children: [
              {
                node: "Form",
                bind: "state:form",
                onSubmit: { type: "mutate" as const, source: "signup" },
                layout: "single-column" as any,
                fields: [
                  { field: "name", label: "Name", required: true, node: "TextInput", placeholder: "Your name" },
                  { field: "email", label: "Email", required: true, node: "TextInput", type: "email", placeholder: "you@company.com" },
                  { field: "password", label: "Password", required: true, node: "TextInput", type: "password", placeholder: "Min 8 characters" },
                ],
                actions: [
                  { node: "Button", label: "Create Account", variant: "primary", width: "full", submit: true } as IRNode,
                ],
              } as IRNode,
            ],
          } as IRNode,
          { node: "Text", content: "Already have an account? Sign in", typography: "body-sm" as const, align: "center" } as IRNode,
        ],
      } as IRNode,
    ],
  };
}
