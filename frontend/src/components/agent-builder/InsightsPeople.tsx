"use client";

/**
 * "Who is using it": how many people used the assistant, how many were new, a column for each day, usage by role and the most active
 * people. Only a live app has this (a development snapshot does not know people).
 *
 * People are only ever an anonymous code (a keyed hash the app makes of its own user id), never a name or an email, and the screen says
 * so. Counts of people come from a sketch that is within 1%, so they read "about". Money is an estimate. Every chart has a table with the
 * same numbers, and the empty cases say in plain words what is missing.
 */
import { ago, dayLabel, formatCount, formatMoney, formatPct, peopleCount, shortKey, type People } from "@/lib/agent-insights";
import { ColumnChart, RoleBars, ShareBar, type DayDatum } from "./insights-charts";
import { ChartCard, CopyButton, Empty, Section, StatTile } from "./insights-parts";

export function InsightsPeople({ users }: { users: People }) {
  const about = users.approximate;
  const days: DayDatum[] = users.activeByDay.map((d) => ({ day: d.day, turns: d.active, errors: 0, usd: null }));
  const anyActive = days.some((d) => d.turns > 0);
  const nobody = users.active === 0 && users.top.length === 0;

  return (
    <Section title="Who is using it" id="people" hint="People are shown by an anonymous code, not a name or an email.">
      {nobody ? (
        <Empty>Nobody has used the assistant in this time.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="insights-people-cards">
            <StatTile id="people-active" label="People using it" value={formatCount(users.active)} prefix={about ? "about" : undefined} sub="Used the assistant in this time" />
            <StatTile id="people-new" label="New people" value={formatCount(users.newUsers)} prefix={about ? "about" : undefined} sub="Used it for the first time" />
            <StatTile id="people-returning" label="Returning people" value={formatCount(users.returning)} prefix={about ? "about" : undefined} sub="Had used it before" />
          </div>
          {about && (
            <p className="text-[11px] text-muted-foreground" data-testid="insights-people-about">
              Counts of people are about right (within 1%), not exact. Counts of replies are exact.
            </p>
          )}

          <div className="rounded-xl border bg-white p-4 shadow-sm" data-testid="insights-people-split">
            <div className="mb-2 text-xs font-medium">New and returning people</div>
            <ShareBar
              label="New and returning people"
              approximate={about}
              parts={[
                { name: "New", value: users.newUsers, tone: "s1" },
                { name: "Returning", value: users.returning, tone: "s2" },
              ]}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ChartCard
              id="people-days"
              title="People active each day"
              subtitle="One column for each day: how many different people used it"
              empty={days.length === 0 || !anyActive ? "No days with people in this time." : null}
              table={<ActiveTable users={users} />}
            >
              <ColumnChart days={days} what="People active each day" noun={["person", "people"]} />
            </ChartCard>

            <ChartCard
              id="people-roles"
              title="Usage by role"
              subtitle="Replies for each kind of person, busiest first"
              empty={users.byRole.length === 0 ? "No roles were recorded in this time." : null}
              table={<RoleTable users={users} />}
            >
              <RoleBars roles={users.byRole} approximate={about} />
            </ChartCard>
          </div>

          <section className="min-w-0 rounded-xl border bg-white p-4 shadow-sm" data-testid="insights-section-people-top" aria-labelledby="insights-h-people-top">
            <h4 id="insights-h-people-top" className="text-sm font-semibold">Most active people</h4>
            <p className="mb-3 text-[11px] text-muted-foreground">
              The 20 people with the most replies. The code is not a name: copy it to look the same person up in your own app.
            </p>
            {users.top.length === 0 ? <Empty>No individual people to list in this time.</Empty> : <TopTable users={users} />}
          </section>
        </div>
      )}
    </Section>
  );
}

const th = "px-2 py-1.5 font-medium";

function ActiveTable({ users }: { users: People }) {
  return (
    <div className="max-h-72 overflow-auto" data-testid="insights-people-days-table">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">People active each day</caption>
        <thead className="sticky top-0 bg-white text-[11px] text-muted-foreground">
          <tr className="border-b">
            <th className={th}>Day</th>
            <th className={`${th} text-right`}>{users.approximate ? "People (about)" : "People"}</th>
          </tr>
        </thead>
        <tbody>
          {[...users.activeByDay].reverse().map((d) => (
            <tr key={d.day} className="border-b last:border-b-0">
              <td className="px-2 py-1.5">{dayLabel(d.day)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatCount(d.active)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoleTable({ users }: { users: People }) {
  return (
    <div className="overflow-x-auto" data-testid="insights-role-table">
      <table className="w-full min-w-[520px] text-left text-xs">
        <caption className="sr-only">Usage by role</caption>
        <thead className="text-[11px] text-muted-foreground">
          <tr className="border-b">
            <th className={th}>Role</th>
            <th className={`${th} text-right`}>Replies</th>
            <th className={`${th} text-right`}>People</th>
            <th className={`${th} text-right`}>Estimated cost</th>
            <th className={`${th} text-right`}>Thumbs down</th>
          </tr>
        </thead>
        <tbody>
          {users.byRole.map((r, i) => (
            <tr key={`${r.role}-${i}`} className="border-b last:border-b-0">
              <td className="px-2 py-2">{r.role}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatCount(r.turns)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{peopleCount(r.users, users.approximate)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{r.usd === null ? "price unknown" : formatMoney(r.usd)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{r.thumbsDownPct === null ? "no ratings yet" : formatPct(r.thumbsDownPct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TopTable({ users }: { users: People }) {
  return (
    <div className="overflow-x-auto" data-testid="insights-top-table">
      <table className="w-full min-w-[640px] text-left text-xs">
        <caption className="sr-only">The most active people</caption>
        <thead className="text-[11px] text-muted-foreground">
          <tr className="border-b">
            <th className={th}>Person code</th>
            <th className={th}>Role</th>
            <th className={`${th} text-right`}>Replies</th>
            <th className={`${th} text-right`}>Estimated cost</th>
            <th className={`${th} text-right`}>Thumbs down</th>
            <th className={`${th} text-right`}>Failed</th>
            <th className={`${th} text-right`}>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {users.top.map((p, i) => (
            <tr key={`${p.userKey}-${i}`} className="border-b last:border-b-0" data-testid="insights-top-row">
              <td className="px-2 py-1.5">
                <span className="inline-flex items-center gap-2">
                  <span className="font-mono text-[11px]" title={p.userKey}>{shortKey(p.userKey)}</span>
                  <CopyButton text={p.userKey} ariaLabel={`Copy the person code ${shortKey(p.userKey)}`} />
                </span>
              </td>
              <td className="px-2 py-2">{p.role ?? "no role"}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatCount(p.turns)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{p.usd === null ? "price unknown" : formatMoney(p.usd)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatCount(p.thumbsDown)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatCount(p.errors)}</td>
              <td className="px-2 py-2 text-right text-muted-foreground">{ago(p.lastSeenAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
