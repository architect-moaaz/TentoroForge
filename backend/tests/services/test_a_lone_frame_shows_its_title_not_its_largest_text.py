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
