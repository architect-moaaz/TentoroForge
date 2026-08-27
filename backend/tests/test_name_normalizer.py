from services.name_normalizer import to_table, to_slug, to_camel, to_singular, name_family


def test_multiword():
    f = name_family("RecruitmentDrive")
    assert f["table"] == "recruitmentDrives"      # camelCase plural
    assert f["slug"] == "recruitment-drives"      # kebab plural
    assert f["camel"] == "recruitmentDrive"
    assert f["id"] == "recruitment-drive"         # kebab SINGULAR (stable join key)
    assert f["singular"] == "recruitmentDrive"


def test_uncountable_equipment():
    # the live bug: must be ONE consistent pair, and honor no double-pluralization surprises
    f = name_family("Equipment")
    assert f["table"] == to_table("Equipment")
    assert f["slug"] == to_slug("Equipment")
    # table and slug agree on plurality (both plural of the SAME base)
    assert f["table"].lower().replace("-", "") == f["slug"].replace("-", "")


def test_table_hint_honored():
    f = name_family("Equipment", table_hint="equipment")
    assert f["table"] == "equipment"              # explicit hint wins, not re-pluralized
    assert f["id"] == "equipment"                 # id stays kebab-singular of the name


def test_trio_cross_check():
    assert to_table("RecruitmentDrive") == "recruitmentDrives"
    assert to_slug("RecruitmentDrive") == "recruitment-drives"
    # y → ies rule survived the copy
    assert to_slug("Category") == "categories"
    # s/sh/ch/x/z → es rule survived the copy
    assert to_slug("Class") == "classes"


def test_equipment_hint_id():
    f = name_family("Equipment", table_hint="equipment")
    assert f["table"] == "equipment"
    assert f["id"] == "equipment"
