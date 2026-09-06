"""The scheme a frame uses, read off what it paints: the ground is the largest
surface, the rail the largest surface that contrasts with it, the accent the
saturated fill on labelled elements. On 2026-09-06 a legislative dashboard
came out with a green page ground, a pink rail and a green accent because
eleven 6px status bars outnumbered one 1031x764 light container, and the
two red buttons tied with the two green chips."""
from services.figma.palette import from_code

FRAME = '''
<div className="bg-white content-stretch flex flex-col size-full" data-name="Root">
  <div className="bg-[#f3f3f1] flex h-[764px] w-[1031px]" data-name="App">
    <div className="bg-[#0d0d0d] flex flex-col h-full w-[238px]" data-name="Sidebar">
      <div className="bg-[#7f1d1d] h-[60px] w-[214px]"><p className="text-[#ffffff]">لوحة التحكم</p></div>
      <div className="bg-[#ce1126] h-[32px] w-[200px]"><p className="text-[#ffffff]">انتقل إلى غرفة التصويت</p></div>
    </div>
    <div className="flex-1 h-full">
      <div className="bg-[#ffffff] border-[#e5e7eb] h-[110px] w-[172px]"><p className="text-[#0d0d0d]">132</p><p className="text-[#6b7280]">عضواً نشطاً</p></div>
      <div className="bg-[#ffffff] border-[#e5e7eb] h-[110px] w-[172px]"><p className="text-[#0d0d0d]">15</p><p className="text-[#6b7280]">جلسات</p></div>
      <div className="bg-[#e6f4ed] h-[24px] w-[120px]"><p className="text-[#007a3d]">جلسة منعقدة</p></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-[6px] w-[80px]"></div>
      <div className="bg-[#007a3d] h-full w-[2px]"></div>
      <div className="bg-[#edf2ef] h-[6px] w-[80px]"></div>
      <div className="bg-[#edf2ef] h-[6px] w-[80px]"></div>
      <div className="bg-[#ce1126] h-[32px] w-[120px]"><p className="text-[#ffffff]">تصويت</p></div>
      <p className="text-[#0d0d0d] font-['Cairo:Bold',sans-serif]">الجلسات القادمة</p>
      <p className="text-[#0d0d0d] font-['Cairo:Regular',sans-serif]">قاعة اللجنة</p>
      <p className="text-[#6b7280] font-['Cairo:Regular',sans-serif]">10:00</p>
    </div>
  </div>
</div>
'''


def test_the_ground_is_the_largest_surface_not_the_most_frequent_fill():
    out = from_code([FRAME])
    assert out["colors"]["background"] == "#f3f3f1"
    assert out["evidence"]["background"] == 1031 * 764


def test_the_rail_is_the_largest_contrasting_surface():
    out = from_code([FRAME])
    assert out["colors"]["sidebarBackground"] == "#0d0d0d"


def test_the_accent_is_what_you_press_not_what_is_drawn_most():
    out = from_code([FRAME])
    assert out["colors"]["primary"] == "#ce1126"
    assert out["evidence"]["primary"] == 2


def test_text_and_type_are_read_as_before():
    out = from_code([FRAME])
    assert out["colors"]["foreground"] == "#0d0d0d"
    assert out["colors"]["mutedForeground"] == "#6b7280"
    assert out["typography"]["fontFamilyBase"] == "Cairo"


def test_a_sketch_yields_nothing():
    assert from_code(['<div className="bg-[#ffffff] w-[10px] h-[10px]"></div>']) == {}
