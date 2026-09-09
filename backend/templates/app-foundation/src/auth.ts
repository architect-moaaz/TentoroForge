import type { NextAuthOptions } from "next-auth";
import { getServerSession } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        try {
          const [user] = await db
            .select()
            .from(users)
            .where(eq(users.email, credentials.email))
            .limit(1);

          if (!user) return null;
          // Only check isActive if the field exists (not all schemas have it)
          if ("isActive" in user && !(user as any).isActive) return null;

          const valid = await bcrypt.compare(
            credentials.password,
            (user as any).password
          );
          if (!valid) return null;

          return {
            id: user.id,
            email: user.email,
            name: (user as any).name || `${(user as any).firstName || ""} ${(user as any).lastName || ""}`.trim(),
            // An explicit role wins; otherwise the account type chosen at
            // signup stands in, so an app whose only role signal is the
            // signup choice still drives menu visibility off it.
            role: (user as any).role || (user as any).accountType || "user",
            accountType: (user as any).accountType || null,
          };
        } catch (error) {
          console.error("Auth error:", error);
          return null;
        }
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
        token.role = (user as any).role;
        token.accountType = (user as any).accountType ?? null;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token) {
        (session.user as any).id = token.id;
        (session.user as any).role = token.role;
        (session.user as any).accountType = (token as any).accountType ?? null;
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET || "dev-secret",
};

export async function auth() {
  return getServerSession(authOptions);
}

declare module "next-auth" {
  interface User { id: string; role?: string; accountType?: string | null; }
  interface Session { user: { id: string; role?: string; accountType?: string | null; name?: string | null; email?: string | null; image?: string | null; }; }
}
declare module "next-auth/jwt" {
  interface JWT { id: string; role?: string; accountType?: string | null; }
}
