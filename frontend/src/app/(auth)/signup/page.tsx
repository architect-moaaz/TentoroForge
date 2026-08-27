"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";

export default function SignupPage() {
  const router = useRouter();
  const { signup, isLoading, error, clearError } = useAuthStore();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await signup(email, name, password);
      router.push("/");
    } catch {
      // error is set in store
    }
  }

  return (
    <div>
      {/* Mobile logo */}
      <div className="mb-8 lg:hidden">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white">
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <span className="text-lg font-semibold text-slate-900 dark:text-white">Tentoro Forge</span>
        </div>
      </div>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
          Create your account
        </h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Get started building with Tentoro Forge
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="name" className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Full name
          </Label>
          <Input
            id="name"
            placeholder="Your name"
            className="h-11"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              clearError();
            }}
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="email" className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Work email
          </Label>
          <Input
            id="email"
            type="email"
            placeholder="you@company.com"
            className="h-11"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              clearError();
            }}
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Password
          </Label>
          <Input
            id="password"
            type="password"
            placeholder="Min 8 characters"
            className="h-11"
            minLength={8}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              clearError();
            }}
            required
          />
          <p className="text-xs text-slate-400">Must include uppercase, lowercase, and a number</p>
        </div>

        <Button
          type="submit"
          className="w-full h-11 text-sm font-medium"
          disabled={isLoading}
        >
          {isLoading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Creating account...
            </>
          ) : (
            <>
              Create account
              <ArrowRight className="ml-2 h-4 w-4" />
            </>
          )}
        </Button>
      </form>

      {/* Divider */}
      <div className="relative my-6">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-slate-200 dark:border-slate-800" />
        </div>
        <div className="relative flex justify-center text-xs">
          <span className="bg-white px-3 text-slate-400 dark:bg-slate-950 dark:text-slate-500">
            or
          </span>
        </div>
      </div>

      {/* Sign in link */}
      <p className="text-center text-sm text-slate-500">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-slate-900 hover:text-slate-700 dark:text-white dark:hover:text-slate-300 transition-colors"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
