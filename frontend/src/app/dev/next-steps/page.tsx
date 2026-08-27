"use client";

/**
 * Dev-only preview for NextStepsCard including the new Verify & Fix
 * chip. Baked messages in existing chats keep their old step list — this
 * page proves the new chip renders + routes correctly on fresh
 * generations.
 */
import { NextStepsCard } from "@/components/chat/NextStepsCard";

export default function NextStepsPreview() {
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6 text-sm">
      <h1 className="text-lg font-semibold">
        NextStepsCard — with Verify &amp; Fix
      </h1>
      <NextStepsCard
        onSend={(msg) => alert(`onSend: ${msg}`)}
        onNavigate={(url) => alert(`onNavigate: ${url}`)}
        steps={[
          {
            label: "Add your first Product",
            kind: "navigate",
            url: "/products/new",
            icon: "plus",
            rationale: "Your app has a Product entity — try creating one.",
          },
          {
            label: "Verify & Fix",
            kind: "tool",
            message: "Verify the app and fix anything that's broken.",
            icon: "shield-check",
            rationale: "Walk every declared journey and auto-fix failures.",
          },
          {
            label: "Change the theme",
            kind: "send",
            message: "Make the theme more vibrant.",
            icon: "palette",
            rationale: "Colors, typography, and density are all in your control.",
          },
          {
            label: "Publish to the web",
            kind: "tool",
            message: "Publish the app.",
            icon: "rocket",
            rationale: "Deploy to Vercel and share a live URL.",
          },
          {
            label: "Build the mobile app",
            kind: "tool",
            message: "Generate the Android app.",
            icon: "smartphone",
            rationale: "Get an installable APK via Expo EAS.",
          },
        ]}
      />
    </div>
  );
}
