"use client";
// The page a person opens to put this application on their phone or computer. Public: it is where a link or a QR code
// sent to someone who has not signed in leads. It shows only what installing is, never anything of theirs.
import * as React from "react";
import { QRCode } from "@tentoroforge/library";
import { InstallButton, isInstalled, isIOS } from "@/components/PwaRegister";
import { MOBILE } from "@/lib/mobile";

export default function InstallPage() {
  const [address, setAddress] = React.useState("");
  const [name, setName] = React.useState("this app");
  const [installed, setInstalled] = React.useState(false);
  const [ios, setIos] = React.useState(false);

  React.useEffect(() => {
    setAddress(`${window.location.origin}/`);
    setName(document.title.trim() || "this app");
    setInstalled(isInstalled());
    setIos(isIOS());
  }, []);

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-8 px-6 py-12">
      <header>
        <p className="text-sm text-muted-foreground">Install</p>
        <h1 className="font-heading text-4xl font-medium text-primary">{name}</h1>
        <p className="mt-3 text-muted-foreground">
          Put it on your home screen. It opens full-screen like an app, with no app store and nothing to download.
        </p>
      </header>

      {!MOBILE.installable ? (
        <p className="rounded-lg bg-card p-5 text-foreground shadow-sm">This app is not set up to be installed.</p>
      ) : installed ? (
        <p className="rounded-lg bg-card p-5 text-foreground shadow-sm">
          It is already installed on this device. Open it from your home screen.
        </p>
      ) : (
        <section className="rounded-lg bg-card p-5 shadow-sm">
          {ios ? (
            <ol className="list-decimal space-y-2 pl-5 text-foreground">
              <li>Open this page in Safari.</li>
              <li>Tap the Share button.</li>
              <li>Choose <strong>Add to Home Screen</strong>.</li>
            </ol>
          ) : (
            <div className="space-y-3">
              <InstallButton className="min-h-11 rounded-full bg-accent px-6 text-sm font-medium text-white" />
              <p className="text-sm text-muted-foreground">
                No Install button? Open your browser&apos;s menu and choose <strong>Install app</strong> or{" "}
                <strong>Add to Home screen</strong>.
              </p>
            </div>
          )}
        </section>
      )}

      {address ? (
        <section className="flex items-center gap-5">
          <div className="rounded-lg bg-white p-3 shadow-sm">
            <QRCode value={address} size={132} />
          </div>
          <p className="text-sm text-muted-foreground">On a computer? Scan this with your phone to open the app there.</p>
        </section>
      ) : null}
    </main>
  );
}
