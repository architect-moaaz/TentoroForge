/**
 * The cockpit's way back: a super admin's own tokens are kept aside in the
 * session while they act as a person, and put back when they return — or
 * when the impersonation token runs out.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  COCKPIT_RETURN_KEY, REFRESH_KEY, TOKEN_KEY,
  hasCockpitReturn, readCockpitReturn, restoreCockpitReturn, saveCockpitReturn,
} from "@/lib/auth-storage";

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });

describe("the cockpit return", () => {
  it("is nothing to save when nobody is signed in", () => {
    expect(saveCockpitReturn()).toBe(false);
    expect(hasCockpitReturn()).toBe(false);
  });

  it("keeps the admin's pair aside and puts it back", () => {
    localStorage.setItem(TOKEN_KEY, "admin-access");
    localStorage.setItem(REFRESH_KEY, "admin-refresh");
    expect(saveCockpitReturn()).toBe(true);
    expect(readCockpitReturn()).toMatchObject({ token: "admin-access", refresh_token: "admin-refresh" });

    // The impersonation token takes the slot; it has no refresh.
    localStorage.setItem(TOKEN_KEY, "acting-as-someone");
    localStorage.removeItem(REFRESH_KEY);
    expect(hasCockpitReturn()).toBe(true);

    expect(restoreCockpitReturn()).toBe(true);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("admin-access");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("admin-refresh");
    expect(sessionStorage.getItem(COCKPIT_RETURN_KEY)).toBeNull();
    expect(hasCockpitReturn()).toBe(false);
  });

  it("restores nothing twice", () => {
    localStorage.setItem(TOKEN_KEY, "admin-access");
    saveCockpitReturn();
    expect(restoreCockpitReturn()).toBe(true);
    expect(restoreCockpitReturn()).toBe(false);
  });

  it("shrugs off a corrupt entry", () => {
    sessionStorage.setItem(COCKPIT_RETURN_KEY, "{not json");
    expect(readCockpitReturn()).toBeNull();
    expect(restoreCockpitReturn()).toBe(false);
  });
});
