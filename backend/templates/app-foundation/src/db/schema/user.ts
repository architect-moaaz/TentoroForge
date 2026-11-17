// Default users table — required by auth.ts. Generated apps may extend
// or override per-project; this default keeps a fresh stamp-out compilable
// without forcing the schema agent to run before first build.
import { pgTable, text, boolean, timestamp, uuid, integer, jsonb } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  // uuid to match the id convention every generated entity uses — otherwise a
  // uuid FK column (e.g. assets.assigned_user_id) can't hold a serial user id
  // ("invalid input syntax for type uuid: 1"). The seed inserts no explicit id,
  // so defaultRandom() fills it; auth treats the id opaquely.
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  name: text("name"),
  // The account type the user picked at signup (e.g. the Blueprint's
  // UserAccount.accountType). Nullable: apps whose signup offers no choice
  // never write it, and auth folds it into the session role when present so
  // the menu can gate on which kind of account signed up. Plain text, not a
  // DB enum — the value set is the app's, not the platform's.
  accountType: text("account_type"),
  isActive: boolean("is_active").default(true),
  // The organisation this person is acting in, when the application has
  // several side by side (`security.tenancy`); their membership there gives
  // their role. Null for an application with none.
  activeOrgId: text("active_org_id"),
  // A NEW ACCOUNT PROVES ITS ADDRESS (`signIn.verifyEmail`): "pending" from
  // sign-up until the six-digit code is entered, then "verified". Null for an
  // account made before the application asked — it is never shut out after
  // the fact. Only the code's digest is kept, with its expiry and attempts.
  emailVerification: text("email_verification"),
  emailCodeHash: text("email_code_hash"),
  emailCodeExpiresAt: timestamp("email_code_expires_at"),
  emailCodeSentAt: timestamp("email_code_sent_at"),
  emailCodeAttempts: integer("email_code_attempts").default(0),
  // TWO-STEP SIGN-IN (`lib/sign-in-guard.ts`): on, a password alone opens no
  // session — a six-digit code mailed to the address must follow, unless this
  // browser was trusted for thirty days. Off for every existing account.
  twoStep: boolean("two_step").default(false),
  // THE ONE CODE IN FLIGHT that is not the address proof above: a two-step
  // sign-in, a password reset, or turning two-step on or off (`signInCodeFor`
  // says which, so one cannot be spent as another). Only its keyed digest is
  // kept, with its expiry, when it was sent and the wrong tries so far.
  signInCodeHash: text("sign_in_code_hash"),
  signInCodeFor: text("sign_in_code_for"),
  signInCodeExpiresAt: timestamp("sign_in_code_expires_at"),
  signInCodeSentAt: timestamp("sign_in_code_sent_at"),
  signInCodeAttempts: integer("sign_in_code_attempts").default(0),
  // SIGN-IN PAUSES after five wrong passwords in a row, for fifteen minutes;
  // a right one (or a password reset) sets the count back to nought.
  failedSignIns: integer("failed_sign_ins").default(0),
  signInPausedUntil: timestamp("sign_in_paused_until"),
  // EVERY SESSION THIS PERSON HOLDS, by its id: a session whose id is gone
  // from the list is signed out at its next request ("sign out other
  // devices"). `sessionVersion` is bumped by a password reset and by signing
  // out elsewhere; a session or a trusted browser from before it is refused.
  signedInDevices: jsonb("signed_in_devices").default([]),
  sessionVersion: integer("session_version").default(0),
  createdAt: timestamp("created_at").defaultNow(),
});
