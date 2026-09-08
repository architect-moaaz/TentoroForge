"""What a frame shows is the destination its rail names.

Fifteen frames of one file each opened with a breadcrumb — "Criterion /
Ticket Queue" — so the first lettered text of every content region was the
brand, the planner had fifteen frames called "Criterion", and it routed them
by position: the Ticket Queue became /dashboard and 14 of 15 were wrong. The
rail lists the places a screen can be; the title is the one of them the
content shows, drawn largest, and among equals the later one, since a
breadcrumb lists ancestors first.
"""
from services.figma.reference import DesignReference, DesignTokens, ScreenRef
from services.figma.store import _frame_headings
from services.figma.url import FigmaTarget

RAIL = '''
      <div className="bg-[#0f172a] content-stretch flex flex-col h-full items-start w-[240px]" data-node-id="{rail}" data-name="Sidebar">
        <p className="font-['Inter:Semi_Bold'] text-[#c9a84c] text-[12px] uppercase">Criterion</p>
        <p className="font-['Inter:Regular'] text-[#7c8ba0] text-[13px]">⬡Dashboard</p>
        <p className="font-['Inter:Regular'] text-[#7c8ba0] text-[13px]">Front Desk</p>
        <p className="font-['Inter:Regular'] text-[#7c8ba0] text-[13px]">+New Case</p>
        <p className="font-['Inter:Regular'] text-[#7c8ba0] text-[13px]">Ticket Queue</p>
      </div>'''


def _frame(node: str, rail: str, crumbs: list[str], heading: str, section: str) -> str:
    crumb_ps = "".join(
        f'<p className="font-[\'Inter:Regular\'] text-[#c9a84c] text-[12px]">{c}</p>'
        f'<p className="text-[#c9a84c] text-[12px]">/</p>' for c in crumbs[:-1]
    ) + f'<p className="font-[\'Inter:Regular\'] text-[#1c1917] text-[12px]">{crumbs[-1]}</p>'
    return f'''
<div className="bg-white content-stretch flex flex-col size-full" data-node-id="{node}" data-name="Refund & Case Management Platform">
  <div className="bg-[#faf7f2] content-stretch flex h-[820px] items-start w-[1280px]" data-node-id="{node}0">
    {RAIL.format(rail=rail)}
    <div className="content-stretch flex flex-[1040_0_0] flex-col h-full items-start" data-node-id="{node}1" data-name="Content">
      <div className="bg-white content-stretch flex items-center justify-between w-full h-[48px]" data-node-id="{node}2" data-name="Topbar">
        {crumb_ps}
        <p className="font-['Inter:Regular'] text-[#57534e] text-[12px]">Zedwell Piccadilly · Zedwell</p>
      </div>
      <p className="font-['Fraunces:SemiBold'] text-[#1c1917] text-[24px]">{heading}</p>
      <p className="font-['Inter:Regular'] text-[#57534e] text-[13px]">Operational tickets auto-routed by category.</p>
      <p className="font-['Fraunces:SemiBold'] text-[#1c1917] text-[20px]">{section}</p>
    </div>
  </div>
</div>'''


def _ref(screens: list[tuple[str, str]]) -> DesignReference:
    return DesignReference(
        target=FigmaTarget(file_key="llRwGmNM8NX72r9r4gmnEq"), source_id="FIGMA-001",
        screens=[ScreenRef(node_id=node, name="Refund & Case Management Platform", canvas="Page 1",
                           width=1280, height=820,
                           structure={"source": "design_context_code", "code": code, "assets": []})
                 for node, code in screens],
        tokens=DesignTokens())


def test_the_title_is_the_rail_destination_the_content_shows_not_the_brand_crumb():
    ticket_queue = _frame("1:2", "1:9", ["Criterion", "Ticket Queue"], "Ticket Queue", "Recent tickets")
    new_case = _frame("1:360", "1:9", ["Criterion", "Front Desk", "New Case"], "New Case", "Guest details")

    shows = _frame_headings(_ref([("1:2", ticket_queue), ("1:360", new_case)]))

    assert shows == {"1:2": "Ticket Queue", "1:360": "New Case"}


def test_a_frame_whose_heading_the_rail_does_not_name_shows_the_crumb_after_the_brand():
    """The dashboard's heading reads "Operations Dashboard"; its rail says
    "Dashboard". The crumb after the brand is the destination the rail names."""
    dashboard = _frame("1:2", "1:9", ["Criterion", "Dashboard"], "Operations Dashboard", "Case volume")
    other = _frame("1:360", "1:9", ["Criterion", "Front Desk"], "Front Desk", "Recent guests")

    shows = _frame_headings(_ref([("1:2", dashboard), ("1:360", other)]))

    assert shows["1:2"] == "Dashboard"
