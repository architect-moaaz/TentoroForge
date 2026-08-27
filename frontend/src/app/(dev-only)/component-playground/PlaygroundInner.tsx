"use client";

import {
  Button, Hero, Section, Card, MetricTile, Avatar, Badge, KeyValueList,
  Heading, Skeleton, Alert, Divider, Breadcrumb,
  Sparkline, Chart, DataGrid, Timeline,
  ApprovalStepper, PersonCard, FilterBar, CommandPalette, ActivityFeed,
  EmptyStateRich, DateRangePicker, MultiSelect,
  AppShell, InspectorPanel, TabPanelWithDeepLink,
} from "@tentoroforge/library";

const SECTION = "border-b border-gray-200 px-8 py-6 bg-white";
const TITLE = "text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3";

export default function PlaygroundInner() {
  return (
    <main className="bg-gray-50 min-h-screen">
      <header className="sticky top-0 bg-white border-b border-gray-200 px-8 py-4">
        <h1 className="text-lg font-semibold">Component Playground</h1>
        <p className="text-xs text-gray-500">Visual regression target</p>
      </header>

      <section data-component="Button" className={SECTION}>
        <p className={TITLE}>Button</p>
        <div className="flex gap-3 flex-wrap">
          <Button label="Primary" variant="primary" />
          <Button label="Secondary" variant="secondary" />
          <Button label="Ghost" variant="ghost" />
          <Button label="Danger" variant="danger" />
        </div>
      </section>

      {/* Heading: schema uses `content`, not `text` */}
      <section data-component="Heading" className={SECTION}>
        <p className={TITLE}>Heading</p>
        <Heading level={1} content="Heading 1" />
        <Heading level={2} content="Heading 2" />
        <Heading level={3} content="Heading 3" />
      </section>

      <section data-component="Heading-weight" className={SECTION}>
        <p className={TITLE}>Heading — weight variations</p>
        <Heading level={2} content="Light weight heading" weight="light" />
        <Heading level={2} content="Regular weight heading" weight="regular" />
        <Heading level={2} content="Bold weight heading" weight="bold" />
        <Heading level={2} content="Display weight heading" weight="display" />
      </section>

      {/* Hero: schema requires `layout` prop (enum: centered | split | stacked) */}
      <section data-component="Hero" className={SECTION}>
        <p className={TITLE}>Hero</p>
        <Hero
          eyebrow="Eyebrow text"
          headline="Hero headline"
          subhead="Subhead with explanatory copy"
          layout="centered"
          ctas={[{ label: "Primary CTA", variant: "primary", action: { type: "navigate", to: "/x" } }]}
        />
      </section>

      <section data-component="Hero-role" className={SECTION}>
        <p className={TITLE}>Hero — role variations</p>
        <div className="space-y-6">
          <Hero role="headline" eyebrow="Page header" headline="Headline role" subhead="Full-bleed page header treatment" layout="centered" ctas={[]} />
          <Hero role="banner" eyebrow="Mid-page" headline="Banner role" subhead="Default — today's appearance" layout="centered" ctas={[]} />
          <Hero role="inline" headline="Inline role" layout="centered" ctas={[]} />
        </div>
      </section>

      <section data-component="Section-role" className={SECTION}>
        <p className={TITLE}>Section — role variations</p>
        <div className="space-y-4">
          <Section variant="plain" role="headline" title="Headline role">
            <p className="text-sm text-muted-foreground">Top-of-page treatment with bottom border.</p>
          </Section>
          <Section variant="plain" role="content" title="Content role">
            <p className="text-sm text-muted-foreground">Default body section.</p>
          </Section>
          <Section variant="plain" role="aside" title="Aside role">
            <p className="text-sm text-muted-foreground">Sidebar / supporting content.</p>
          </Section>
          <Section variant="plain" role="footer" title="Footer role">
            <p className="text-sm text-muted-foreground">Bottom-of-page treatment with top border.</p>
          </Section>
        </div>
      </section>

      <section data-component="MetricTile" className={SECTION}>
        <p className={TITLE}>MetricTile</p>
        <div className="grid grid-cols-4 gap-3">
          <MetricTile label="Total Users" value={1284} format="number" />
          <MetricTile label="Revenue" value={482910} format="currency" delta={{ direction: "up", value: 0.12 }} />
          <MetricTile label="Conversion" value={0.034} format="percent" delta={{ direction: "down", value: 0.04 }} />
          <MetricTile label="Avg Time" value={142} format="duration" delta={{ direction: "flat", value: 0 }} />
        </div>
      </section>

      <section data-component="MetricTile-importance" className={SECTION}>
        <p className={TITLE}>MetricTile — importance variations</p>
        <div className="grid grid-cols-3 gap-3">
          <MetricTile label="Primary tile" value={482910} format="currency"
                      delta={{ direction: "up", value: 0.18 }} importance="primary" />
          <MetricTile label="Secondary tile" value={1284} format="number"
                      delta={{ direction: "up", value: 0.12 }} importance="secondary" />
          <MetricTile label="Tertiary tile" value={42} format="number" importance="tertiary" />
        </div>
      </section>

      {/* Card: schema has title/footer/elevation + children slot */}
      <section data-component="Card" className={SECTION}>
        <p className={TITLE}>Card</p>
        <Card title="Card title">
          <p className="font-semibold">Card content</p>
          <p className="text-sm text-gray-600">Body copy.</p>
        </Card>
      </section>

      <section data-component="Card-density" className={SECTION}>
        <p className={TITLE}>Card — density variations</p>
        <div className="grid grid-cols-3 gap-3">
          <Card title="Tight" density="tight">
            <p className="text-sm text-gray-600">Compact padding for data-dense layouts.</p>
          </Card>
          <Card title="Regular" density="regular">
            <p className="text-sm text-gray-600">Default — today's appearance.</p>
          </Card>
          <Card title="Loose" density="loose">
            <p className="text-sm text-gray-600">Spacious padding for featured content.</p>
          </Card>
        </div>
      </section>

      <section data-component="Avatar" className={SECTION}>
        <p className={TITLE}>Avatar</p>
        <div className="flex items-center gap-3">
          <Avatar name="Sarah Chen" size="sm" />
          <Avatar name="Marcus Lee" size="md" />
          <Avatar name="Ana Martins" size="lg" />
        </div>
      </section>

      <section data-component="Badge" className={SECTION}>
        <p className={TITLE}>Badge</p>
        <div className="flex gap-2 flex-wrap">
          <Badge content="Active" variant="success" />
          <Badge content="Pending" variant="warning" />
          <Badge content="Failed" variant="danger" />
          <Badge content="Info" variant="primary" />
          <Badge content="Neutral" variant="neutral" />
        </div>
      </section>

      <section data-component="Alert" className={SECTION}>
        <p className={TITLE}>Alert</p>
        <Alert variant="info" title="Heads up" message="This is an info alert." />
      </section>

      {/* KeyValueList: schema uses { label, value, copyable? } */}
      <section data-component="KeyValueList" className={SECTION}>
        <p className={TITLE}>KeyValueList</p>
        <KeyValueList items={[
          { label: "Name", value: "Sarah Chen" },
          { label: "Department", value: "Engineering" },
          { label: "Joined", value: "2022-04-15" },
        ]} />
      </section>

      {/* Skeleton: schema uses variant (rect/circle/text) + optional lines — not width/height */}
      <section data-component="Skeleton" className={SECTION}>
        <p className={TITLE}>Skeleton</p>
        <div className="space-y-4">
          <Skeleton variant="text" lines={3} />
          <Skeleton variant="rect" />
          <Skeleton variant="circle" />
        </div>
      </section>

      <section data-component="Breadcrumb" className={SECTION}>
        <p className={TITLE}>Breadcrumb</p>
        <Breadcrumb items={[
          { label: "Home", href: "/" },
          { label: "Users", href: "/users" },
          { label: "Sarah Chen" },
        ]} />
      </section>

      <section data-component="Divider" className={SECTION}>
        <p className={TITLE}>Divider</p>
        <Divider />
      </section>

      <section data-component="Sparkline" className={SECTION}>
        <p className={TITLE}>Sparkline</p>
        <div className="flex items-center gap-4">
          <Sparkline data={[2,4,3,7,6,9,8]} color="hsl(221.2 83.2% 53.3%)" />
          <Sparkline data={[10,8,9,5,6,3,2]} color="hsl(0 84.2% 60.2%)" />
          <Sparkline data={[5,5,5,6,5,5,5]} color="hsl(215.4 16.3% 46.9%)" showDots />
        </div>
      </section>

      <section data-component="Chart" className={SECTION}>
        <p className={TITLE}>Chart — line</p>
        <Chart chartType="line" data={[
          {month:"Jan", users:100, revenue:120},
          {month:"Feb", users:150, revenue:180},
          {month:"Mar", users:140, revenue:170},
          {month:"Apr", users:200, revenue:240},
          {month:"May", users:220, revenue:280},
        ]} xKey="month" series={[
          {name:"Users", dataKey:"users"},
          {name:"Revenue", dataKey:"revenue"},
        ]} height={200} />
      </section>

      <section data-component="DataGrid" className={SECTION}>
        <p className={TITLE}>DataGrid</p>
        <DataGrid
          columns={[
            {key:"name",       label:"Name",       sortable:true, frozen:true, width:160},
            {key:"department", label:"Department", sortable:true},
            {key:"role",       label:"Role"},
            {key:"status",     label:"Status",     align:"right" as const},
          ]}
          rows={[
            {id:"1", name:"Sarah Chen",     department:"Engineering", role:"Senior Eng",       status:"Active"},
            {id:"2", name:"Marcus Lee",     department:"Engineering", role:"Manager",          status:"Active"},
            {id:"3", name:"Ana Martins",    department:"Design",      role:"Product Designer", status:"On Leave"},
            {id:"4", name:"Kenji Tanaka",   department:"Engineering", role:"Staff Eng",        status:"Active"},
          ]}
          rowKey="id"
          selectable
        />
      </section>

      <section data-component="Timeline" className={SECTION}>
        <p className={TITLE}>Timeline</p>
        <Timeline entries={[
          {id:"1", timestamp:"2026-05-01T09:00:00Z", actor:"Sarah Chen",            status:"info" as const,
           title:"Submitted leave request"},
          {id:"2", timestamp:"2026-05-01T14:30:00Z", actor:"Marcus Lee (manager)", status:"approved" as const,
           title:"Approved request", detail:"Coverage confirmed via Diego."},
          {id:"3", timestamp:"2026-05-02T10:00:00Z", actor:"HR System",            status:"completed" as const,
           title:"Request finalised + calendar updated"},
        ]} />
      </section>

      <section data-component="ApprovalStepper" className={SECTION}>
        <p className={TITLE}>ApprovalStepper</p>
        <ApprovalStepper steps={[
          { id: "1", label: "Submitted",      status: "approved", actor: "Sarah Chen",   timestamp: "2026-04-29T09:00:00Z" },
          { id: "2", label: "Manager Review", status: "approved", actor: "Marcus Lee",   timestamp: "2026-04-30T14:00:00Z" },
          { id: "3", label: "HR Review",      status: "current",  actor: "Priya Shah" },
          { id: "4", label: "Final",          status: "pending" },
        ]} />
      </section>

      <section data-component="PersonCard" className={SECTION}>
        <p className={TITLE}>PersonCard — compact + expanded</p>
        <div className="flex gap-6">
          <PersonCard name="Sarah Chen" role="Senior Engineer" status="active" />
          <div className="w-64">
            <PersonCard name="Marcus Lee" role="Engineering Manager" department="Engineering"
                        email="marcus.lee@example.com" status="active"
                        manager={{ name: "Diego Alvarez", role: "VP Engineering" }}
                        layout="expanded" />
          </div>
        </div>
      </section>

      <section data-component="FilterBar" className={SECTION}>
        <p className={TITLE}>FilterBar</p>
        <FilterBar
          showSearch
          chips={[
            { key: "dept", label: "Department", options: [
              { value: "eng", label: "Engineering" },
              { value: "design", label: "Design" },
              { value: "sales", label: "Sales" },
            ]},
            { key: "status", label: "Status", options: [
              { value: "active", label: "Active" },
              { value: "leave", label: "On Leave" },
            ]},
          ]}
          savedViews={[
            { id: "recent-eng", label: "Recent Engineering Hires", filters: { dept: "eng" } },
          ]}
        />
      </section>

      <section data-component="CommandPalette" className={SECTION}>
        <p className={TITLE}>CommandPalette — Cmd+K to open</p>
        <CommandPalette items={[
          { id: "n1", label: "New Leave Request",   group: "Actions", shortcut: "⌘N",
            action: { type: "navigate", to: "/leave-requests/new" }},
          { id: "n2", label: "Browse Employees",    group: "Pages",
            action: { type: "navigate", to: "/employees" }},
          { id: "n3", label: "Approve all pending", group: "Actions",
            action: { type: "workflow", workflow: "ApproveAllPending" }},
        ]} />
      </section>

      <section data-component="ActivityFeed" className={SECTION}>
        <p className={TITLE}>ActivityFeed</p>
        <div className="max-w-md">
          <ActivityFeed entries={[
            { id: "1", timestamp: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
              actor: { name: "Sarah Chen" }, action: "approved", target: "Q1 Vacation Request",
              category: "approve" },
            { id: "2", timestamp: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
              actor: { name: "Marcus Lee" }, action: "commented on", target: "Engineering Hiring Plan",
              detail: "Great progress; let’s discuss Q2 priorities tomorrow.",
              category: "comment" },
            { id: "3", timestamp: new Date(Date.now() - 86400 * 1000).toISOString(),
              actor: { name: "HR System" }, action: "created", target: "Annual Review Cycle",
              category: "system" },
          ]} />
        </div>
      </section>

      <section data-component="EmptyStateRich" className={SECTION}>
        <p className={TITLE}>EmptyStateRich</p>
        <div className="max-w-lg">
          <EmptyStateRich
            icon="calendar"
            heading="No leave requests yet"
            body="Submit your first PTO request to see it tracked here, including approval status and remaining balance."
            primaryCta={{ label: "Submit a Request", action: { type: "navigate", to: "/leave-requests/new" }}}
            sampleDataLink={{ label: "Try with sample data", action: { type: "workflow", workflow: "SeedSampleLeaveData" }}}
          />
        </div>
      </section>

      <section data-component="DateRangePicker" className={SECTION}>
        <p className={TITLE}>DateRangePicker</p>
        <DateRangePicker name="reportRange" label="Date range" />
      </section>

      <section data-component="MultiSelect" className={SECTION}>
        <p className={TITLE}>MultiSelect</p>
        <MultiSelect
          name="depts"
          label="Departments"
          placeholder="All departments"
          options={[
            { value: "eng", label: "Engineering" },
            { value: "design", label: "Design" },
            { value: "sales", label: "Sales" },
            { value: "ops", label: "Operations" },
            { value: "hr", label: "HR" },
          ]}
        />
      </section>

      <section data-component="AppShell" className={SECTION}>
        <p className={TITLE}>AppShell</p>
        <div className="border border-border rounded-md overflow-hidden" style={{ height: 400 }}>
          <AppShell
            sidebar={<nav className="p-3 text-xs text-sidebar-foreground/80 space-y-1">
              <div className="font-semibold uppercase tracking-wide opacity-60 mb-2">Pages</div>
              <div className="px-2 py-1 rounded bg-sidebar-active/40">Dashboard</div>
              <div className="px-2 py-1 rounded">Employees</div>
              <div className="px-2 py-1 rounded">Leave Requests</div>
            </nav>}
            topbar={<div className="text-xs text-muted-foreground">Home / Dashboard</div>}
            actions={<button className="h-8 px-3 rounded-md bg-primary text-primary-foreground text-xs font-medium">+ New</button>}
          >
            <p className="text-sm text-muted-foreground">Main content area.</p>
          </AppShell>
        </div>
      </section>

      <section data-component="InspectorPanel" className={SECTION}>
        <p className={TITLE}>InspectorPanel — open by adding ?inspector=demo to URL</p>
        <p className="text-xs text-muted-foreground mb-3">
          The InspectorPanel is hidden by default. Try{" "}
          <a href="?inspector=demo" className="underline text-primary">this link</a>{" "}
          to open it.
        </p>
        <InspectorPanel paramKey="inspector" title="Sample Detail" width="default">
          <div className="space-y-3 text-sm">
            <p>Inspector content goes here.</p>
            <p className="text-muted-foreground">Press Esc or click outside to close.</p>
          </div>
        </InspectorPanel>
      </section>

      <section data-component="TabPanelWithDeepLink" className={SECTION}>
        <p className={TITLE}>TabPanelWithDeepLink — active tab persists in URL ?tab=...</p>
        <TabPanelWithDeepLink
          paramKey="demo_tab"
          tabs={[
            { id: "overview",  label: "Overview" },
            { id: "history",   label: "History" },
            { id: "settings",  label: "Settings" },
          ]}
          defaultTab="overview"
        >
          <div className="text-sm">Overview content — first tab</div>
          <div className="text-sm">History content — second tab</div>
          <div className="text-sm">Settings content — third tab</div>
        </TabPanelWithDeepLink>
      </section>
    </main>
  );
}
