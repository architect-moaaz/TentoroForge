"""What a frame shows is its title. A single legislative dashboard frame had
only KPI numbers large enough to be Headings, so the page was named "132";
its rail came first in document order, so removing nothing would have named
it after the brand. The title is the first lettered text of the widest region
of the frame's first row."""
from services.figma.store import _frame_headings
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget
from services.figma.reference import DesignTokens

FRAME = '''
<div className="bg-white content-stretch flex flex-col size-full" data-node-id="1:2" data-name="Platform">
  <div className="bg-[#f3f3f1] content-stretch flex h-[764px] items-start w-[1031px]" data-node-id="1:5">
    <div className="bg-[#0d0d0d] content-stretch flex flex-col h-full items-start w-[240px]" data-node-id="1:6" data-name="Sidebar">
      <p className="font-['Cairo:Bold',sans-serif] text-[#ffffff] text-[15px]">المجلس التشريعي</p>
      <p className="font-['Cairo:Regular',sans-serif] text-[#8a8a8a] text-[11px]">نظام إدارة الأعمال التشريعية</p>
      <p className="font-['Cairo:Regular',sans-serif] text-[#ffffff] text-[13px]">الجلسات والأجندات</p>
      <p className="font-['Cairo:Regular',sans-serif] text-[#ffffff] text-[13px]">اللجان والهيئات</p>
    </div>
    <div className="content-stretch flex flex-[791_0_0] flex-col h-full items-start" data-node-id="1:7" data-name="Content">
      <div className="bg-white content-stretch flex items-center justify-between w-full h-[56px]" data-node-id="1:8" data-name="Topbar">
        <p className="font-['Cairo:Regular',sans-serif] text-[#0d0d0d] text-[14px]">لوحة التحكم</p>
        <p className="font-['Cairo:Regular',sans-serif] text-[#7a9b85] text-[12px]">الأحد، 31 أغسطس 2026</p>
      </div>
      <div className="bg-white content-stretch flex flex-col w-[172px] h-[110px]" data-node-id="1:9" data-name="Kpi">
        <p className="font-['Cairo:Regular',sans-serif] text-[#7a9b85] text-[12px]">أعضاء المجلس</p>
        <p className="font-['Cairo:Bold',sans-serif] text-[#0d0d0d] text-[28px]">132</p>
      </div>
      <p className="font-['Cairo:Bold',sans-serif] text-[#0d0d0d] text-[20px]">الجلسات القادمة</p>
    </div>
  </div>
</div>
'''


def _ref():
    screen = ScreenRef(node_id="1:2", name="Platform", canvas="Page 1", width=1031, height=764,
                       structure={"source": "design_context_code", "code": FRAME, "assets": []})
    return DesignReference(target=FigmaTarget(file_key="m17vMkD0GiMtLog7IH24cV"), source_id="FIGMA-001",
                           screens=[screen], tokens=DesignTokens())


def test_the_title_is_the_header_text_not_the_kpi_nor_the_brand():
    shows = _frame_headings(_ref())
    assert shows == {"1:2": "لوحة التحكم"}


def test_a_lone_frames_rail_is_its_navigation():
    """One screen shares nothing with itself, so its rail composed as page
    content beside the shell's own rail. The lone rail is the narrower,
    label-heavy column of the first row; its icon+label items are the
    destinations, its logo the brand, its filled status card neither."""
    from services.jsx_to_schema import transform_jsx_to_schema
    from services.figma import chrome
    code = '''<div className="bg-white flex flex-col size-full" data-node-id="1:2">
  <div className="bg-[#f3f3f1] flex h-[764px] items-start w-[1031px]" data-node-id="1:5">
    <div className="bg-[#0d0d0d] flex flex-col h-full items-start w-[240px]" data-node-id="1:6" data-name="Sidebar">
      <div className="flex items-center gap-2" data-node-id="1:7" data-name="Brand"><img alt="" className="size-[40px]" src="/flag.svg" /><p className="text-white">المجلس التشريعي</p><p className="text-[#8a8a8a]">نظام إدارة الأعمال التشريعية</p></div>
      <div className="bg-[#0f2a1a] flex flex-col" data-node-id="1:8" data-name="Session"><p className="text-white">جلسة منعقدة</p><p className="text-white">الجلسة العادية 2026/15</p><p className="text-white">الأحد 31 أغسطس 2026</p></div>
      <div className="flex items-center gap-2" data-node-id="1:9" data-name="Button"><img alt="" className="size-[20px]" src="/i1.svg" /><p className="text-white">لوحة التحكم</p><p className="text-[#8a8a8a]">نظرة عامة</p></div>
      <div className="flex items-center gap-2" data-node-id="1:10" data-name="Button"><img alt="" className="size-[20px]" src="/i2.svg" /><p className="text-white">الجلسات والأجندات</p><p className="text-[#8a8a8a]">إدارة الجلسات</p><p className="text-white">2</p></div>
      <div className="flex items-center gap-2" data-node-id="1:11" data-name="Button"><img alt="" className="size-[20px]" src="/i3.svg" /><p className="text-white">اللجان والهيئات</p></div>
    </div>
    <div className="flex flex-[791_0_0] flex-col h-full items-start" data-node-id="1:12" data-name="Content">
      <p className="text-[#0d0d0d]">لوحة التحكم</p>
      <div className="bg-[#ce1126] flex items-center rounded-[8px]" data-node-id="1:13" data-name="Button"><p className="text-white">عرض الكل</p><p className="text-white">←</p></div>
    </div>
  </div>
</div>'''
    from unittest.mock import patch
    from services.figma_llm_ctx import set_figma_llm_context, reset_figma_llm_context

    def _bind(label, data_name, class_name):
        return {"navigate": "/sessions"} if "عرض" in label else {}

    set_figma_llm_context(routes=["/", "/sessions"], workflows=None)
    try:
        with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
            root = transform_jsx_to_schema(code, {}, canvas=(1031, 764))["children"][0]
    finally:
        reset_figma_llm_context()
    fps = chrome.chrome_for([root])
    assert fps, "the lone rail is found"
    content, removed = chrome.split(root, fps)
    # THE RAIL AS DRAWN, NOT AS SORTED. Which entry is the brand, the status
    # card or a destination is the architect's reading; what is recorded is
    # what each entry carries.
    drawn = chrome.rail_as_drawn(removed)
    heads = [e["labels"][0] for e in drawn]
    assert heads == ["المجلس التشريعي", "جلسة منعقدة", "لوحة التحكم", "الجلسات والأجندات", "اللجان والهيئات"], heads
    brand, session, *items = drawn
    assert brand["icon"] == 40 and "filled" not in brand
    assert session["filled"] is True and "icon" not in session
    assert [c["labels"] for c in items] == [
        ["لوحة التحكم", "نظرة عامة"], ["الجلسات والأجندات", "إدارة الجلسات", "2"], ["اللجان والهيئات"]]
    assert all(c["icon"] == 20 for c in items)
    text = chrome.describe_drawn(drawn)
    assert "icon 40px" in text and "filled block" in text and "- لوحة التحكم  [underneath: نظرة عامة" in text
    labels = chrome._labels(content, [])
    assert "لوحة التحكم" in labels and "الجلسات والأجندات" not in labels
    buttons = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "Button":
                buttons.append((n.get("props") or {}).get("label"))
            for c in n.get("children") or []:
                walk(c)
    walk(content)
    assert len(buttons) == 1 and str(buttons[0]).startswith("عرض الكل"), buttons
