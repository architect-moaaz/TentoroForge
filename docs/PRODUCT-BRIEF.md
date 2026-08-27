# Tentoro Forge — where we are, where we're going

## What it is, plainly
Most AI app builders give you screens that look finished but don't actually *do*
anything. You still have to go build the real software underneath — the database,
the forms that save, the approvals, the permissions, the logic. That's the hard
part, and that's the part Tentoro Forge builds.

You describe what you want (or hand us a Figma file), and we generate a working
business app: the data model, the screens, the workflows, the rules, and a real
database behind it all. Not a mockup — something you can actually use.

## Where we are now
This isn't a prototype. We've quietly built a lot — somewhere around 150 features
across the platform: orgs and roles, projects with version history, a 24‑step
generation pipeline, a data‑model studio, a workflow engine with approvals and
timers, a rules engine, visual and drag‑and‑drop editors a non‑developer can
actually use, live preview, templates, and cost monitoring.

And the thing that usually trips these products up — we proved it works. This
quarter we took a generated app all the way through: it installed, set up its
database, ran, and saved real records — create, update, delete, all driven by the
workflows we generated, with the buttons wired to the right thing. The "looks done
but does nothing" problem is solved at the core.

## Where we're going

**Right now — getting it launch‑ready.**
The big one is one‑click deploy to the cloud (Kubernetes): hit a button in the
editor and your app goes live with its database and a real URL — no DevOps, no
setup. That's the launch. Alongside it, we're tightening up the last rough edges
so every app you generate just opens and runs.

**Next — making it something teams use together.**
Comments, presence, and chat inside a project. Proper sign‑in (Google/Microsoft/
GitHub, MFA, password reset). Tests that ship with every app, plus dashboards so
you can see what's happening. The stuff that turns a clever tool into something a
company trusts.

**After that — going wider and smarter.**
Generate mobile apps (React Native) from the same project, so web and mobile share
one source of truth. A drop‑in messaging feature for the apps we build. And under
the hood, a smarter generation engine — multiple specialized AI "experts" working
together with deterministic logic where it matters — so the apps come out more
reliable as we scale. Plus a library of ready‑made starters (CRM, inventory,
quoting, asset tracking) for instant wins.

## Why we think we win
- We build the part that actually matters — the data and logic, not just the pretty front.
- People can start where they already are: a sentence or a Figma file.
- Non‑developers can edit it, but it's real code underneath — so nothing's locked
  in and apps can always be extended or exported.
- Soon you'll go from "I made an app" to "my app is live" in one click.
- And honestly, we've already built the boring, hard foundations most competitors
  haven't even started.

## The short version
> Today Tentoro Forge builds real, working business apps — data, screens,
> workflows, rules — from a prompt or a Figma file. Next, it puts them live in one
> click. And we're building the intelligence and teamwork layer to make it the
> fastest way to go from an idea to software a company can actually run on.

---

*Honest footnotes for the room: deploy, collaboration, and mobile are coming, not
shipped — keep them in "where we're going." And there's one known fix in flight for
how generated pages render in the browser, so hold off on "flawless out of the box"
until that lands.*
