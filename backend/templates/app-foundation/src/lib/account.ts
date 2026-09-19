// The person behind a login — projected from the Living Blueprint
// (services/blueprint/account_model.py). Safe on the client: names and field
// specs only; the table lives in `account-table.ts`, which is server-only.
//
// This default is an application with no account entity: signup creates the
// login alone, and a new account lands on the application's home.

export interface AccountField {
  name: string;
  label: string;
  kind: "text" | "textarea" | "email" | "tel" | "url" | "number" | "date" | "select" | "checkbox";
  required: boolean;
  options?: { label: string; value: string }[];
}

/** The entity each login IS (its id is the login's id), and what signup asks for it. */
export const ACCOUNT: null | { entity: string; fields: AccountField[]; labelField: string | null; locationField: string | null } = null;

/** The role a person who creates their own account gets; null leaves the platform default. */
export const SIGNUP_ROLE: string | null = null;

/** Where a new account goes first — the page that satisfies a prerequisite, else home. */
export const AFTER_SIGNUP: string = "/";

/** Where a signed-in person lands. */
export const HOME: string = "/";
