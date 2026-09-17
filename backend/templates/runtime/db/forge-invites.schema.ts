import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";

/**
 * Pending password setups — one row per account waiting for its person to
 * choose a password, whether the account was just created or had its password
 * reset.
 *
 * WHY NOT A COLUMN ON `users`. The obvious place for a one-time token is the
 * users row, and it is the wrong place: `auth.ts` puts every scalar column of
 * that row into the session (so an ownership rule can read its actor column),
 * and the data engine serves the table to whichever roles a Users page admits.
 * A token living there would ride into the browser. A `forge_`-prefixed table
 * is not a Blueprint entity, so nothing projects a page, an API or an access
 * rule over it, and the only code that reads it is the set-password route.
 *
 * ONLY THE HASH IS STORED. `tokenHash` is the SHA-256 of the token in the
 * setup link; the link itself is shown to the owner once and kept nowhere.
 * A leaked database therefore hands nobody a way in, and a token that expires
 * is a token the route refuses.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeInvites = pgTable("forge_invites", {
  id: uuid("id").primaryKey().defaultRandom(),
  // One pending setup per account: issuing a new link supersedes the old one
  // (the insert upserts on this column), so two live links can never open the
  // same account.
  email: text("email").notNull().unique(),
  tokenHash: text("token_hash").notNull(),
  // WHICH ISSUANCE THIS IS, and the reason the row outlives its use. The seed
  // applies the owner's roster on every start, so it must be able to tell an
  // invite it has already applied from a new one — otherwise a link the person
  // used last week would be re-opened, and their password cleared, every time
  // the application restarted. A row is never deleted and never re-applied:
  // `issue` is what the seed looks for.
  issue: text("issue").notNull().unique(),
  // "invite" for a new account, "reset" for one whose password was cleared.
  // What the set-password page says to the person differs; what it does does not.
  purpose: text("purpose").notNull().default("invite"),
  expiresAt: timestamp("expires_at").notNull(),
  // Set the moment the password is chosen. A used link is refused from then on,
  // which is what makes a setup link one-time.
  usedAt: timestamp("used_at"),
  createdAt: timestamp("created_at").defaultNow(),
});
