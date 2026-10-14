// Written by the Blueprint projection (project_sign_in). This default: email
// and password only. Edit the Blueprint, not this file.
export interface SsoEntry {
  id: string;
  name: string;
  kind: "oidc" | "saml";
  provider: "entra" | "google" | "okta" | "oidc" | "saml";
  /** The NAMES of the environment variables the provider is reached with. */
  issuerKey: string;
  clientIdKey: string;
  clientSecretKey: string;
  domains: string[];
  roleFrom: { claim: string; map: Record<string, string>; default: string | null } | null;
  provisioning: "invite_only" | "just_in_time";
}
export interface SignInPolicy { password: boolean; magicLink: boolean; sso: SsoEntry[] }
export const SIGN_IN: SignInPolicy = { password: true, magicLink: false, sso: [] };
