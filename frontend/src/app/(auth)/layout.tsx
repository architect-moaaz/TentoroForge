export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Left: Brand panel */}
      <div className="hidden lg:flex lg:w-[480px] xl:w-[560px] flex-col justify-between bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-10 text-white relative overflow-hidden">
        {/* Decorative elements */}
        <div className="absolute -top-24 -right-24 h-64 w-64 rounded-full bg-blue-500/10 blur-3xl" />
        <div className="absolute bottom-20 -left-20 h-48 w-48 rounded-full bg-indigo-500/10 blur-3xl" />

        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 backdrop-blur-sm border border-white/10">
              <svg className="h-5 w-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <span className="text-xl font-semibold tracking-tight">Tentoro Forge</span>
          </div>
          <p className="text-sm text-slate-400 mt-1 max-w-[280px]">
            Build full-stack apps from conversations and designs
          </p>
        </div>

        <div className="space-y-8 relative z-10">
          <div className="space-y-5">
            {[
              {
                title: "Design to Code",
                desc: "Import Figma designs and get pixel-perfect Next.js apps",
              },
              {
                title: "AI-Powered Generation",
                desc: "Describe what you need — the agents build it for you",
              },
              {
                title: "Visual Editing",
                desc: "Edit your app visually with real-time preview",
              },
            ].map((item) => (
              <div key={item.title} className="flex gap-3">
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/10 border border-white/5">
                  <svg className="h-3.5 w-3.5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <div>
                  <p className="text-sm font-medium text-white">{item.title}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-slate-500">
          &copy; 2026 Tentoro. All rights reserved.
        </p>
      </div>

      {/* Right: Auth form */}
      <div className="flex flex-1 items-center justify-center p-6 sm:p-10 bg-white dark:bg-slate-950">
        <div className="w-full max-w-[420px]">{children}</div>
      </div>
    </div>
  );
}
