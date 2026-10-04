"""Seed rows get a photo found from their own name; no key, a failed search and
a rebuild all behave; only picture-address columns are touched (UAT F&B: blank
squares where the menu photos belong)."""
import json

import pytest

from services.seed_photos import fill_seed_photos, is_photo_column, is_placeholder


def _plan(tmp_path, names=("Iced Lemon Tea", "Spring Rolls"), rows=None):
    (tmp_path / "contracts").mkdir(exist_ok=True)
    rows = rows or [{"id": str(i), "name": n, "imageUrl": f"Image Url {i + 1}"} for i, n in enumerate(names)]
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps({
        "tables": [{"name": "MenuItem", "seed_data": rows}], "sample_data": {"MenuItem": rows}}))
    return tmp_path / "contracts/seed-plan.json"


class Fake:
    def __init__(self, fail_on=()):
        self.queries, self.fail_on, self.n = [], fail_on, 0

    def __call__(self, path, params):
        if path != "/search/photos":
            return {}
        q = params["query"]
        self.queries.append(q)
        if any(f in q for f in self.fail_on):
            raise RuntimeError("boom")
        slug = q.replace(" ", "-")
        return {"results": [{"urls": {"raw": f"https://img/{slug}-{k}?x=1"},
                             "user": {"name": "Ann Lee", "links": {"html": "https://u/ann"}}, "links": {}}
                            for k in range(int(params["per_page"]))]}


def _rows(p):
    return json.loads(p.read_text())["tables"][0]["seed_data"]


def test_key_present_rows_get_photo_and_credit(tmp_path):
    p = _plan(tmp_path)
    r = fill_seed_photos(tmp_path, Fake())
    assert r["found"] == 2
    rows = _rows(p)
    assert rows[0]["imageUrl"].startswith("https://img/iced-lemon-tea-menu-item")
    assert "#credit=Ann%20Lee" in rows[0]["imageUrl"]                      # the credit travels with the address
    plan = json.loads(p.read_text())
    url = rows[0]["imageUrl"].split("#")[0]
    assert plan["seed_photo_credits"][url]["name"] == "Ann Lee"
    assert plan["sample_data"]["MenuItem"][1]["imageUrl"] == rows[1]["imageUrl"]


def test_no_key_leaves_the_column_empty_not_placeholder_text(tmp_path, monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    p = _plan(tmp_path)
    r = fill_seed_photos(tmp_path)
    assert r["found"] == 0 and "no Unsplash key" in r["why"]
    assert [row["imageUrl"] for row in _rows(p)] == ["", ""]


def test_a_failed_search_costs_those_rows_only(tmp_path):
    p = _plan(tmp_path)
    r = fill_seed_photos(tmp_path, Fake(fail_on=("spring",)))
    assert (r["found"], r["empty"]) == (1, 1)
    rows = _rows(p)
    assert rows[0]["imageUrl"].startswith("https://") and rows[1]["imageUrl"] == ""


def test_a_found_photo_is_kept_on_rebuild_without_searching_again(tmp_path):
    p = _plan(tmp_path)
    fill_seed_photos(tmp_path, Fake())
    first = [r["imageUrl"] for r in _rows(p)]
    plan = json.loads(p.read_text())
    for r in plan["tables"][0]["seed_data"]:
        r["imageUrl"] = "Image Url 1"                                          # the synthesizer rewrites the rows
    p.write_text(json.dumps(plan))
    again = Fake()
    fill_seed_photos(tmp_path, again)
    assert again.queries == [] and [r["imageUrl"] for r in _rows(p)] == first


def test_searches_are_deduplicated_capped_and_rows_sharing_a_query_get_different_photos(tmp_path):
    p = _plan(tmp_path, names=["Iced Lemon Tea 1", "Iced Lemon Tea 2", "Iced Lemon Tea 3"])
    f = Fake()
    fill_seed_photos(tmp_path, f)
    assert len(f.queries) == 1
    assert len({r["imageUrl"] for r in _rows(p)}) == 3                          # not one photo three times
    p = _plan(tmp_path, names=[f"Dish {chr(97 + i)}" for i in range(10)])
    f = Fake()
    r = fill_seed_photos(tmp_path, f, max_searches=3)
    assert len(f.queries) == 3 and r["found"] == 3 and r["empty"] == 7


def test_a_long_name_makes_a_capped_query_and_a_category_adds_variety(tmp_path):
    rows = [{"id": "1", "name": "x" * 300, "imageUrl": ""}, {"id": "2", "name": "Pad Thai", "category": "Noodles", "imageUrl": ""}]
    _plan(tmp_path, rows=rows)
    f = Fake()
    fill_seed_photos(tmp_path, f)
    assert all(len(q) <= 100 for q in f.queries) and "pad thai menu item noodles" in f.queries


@pytest.mark.parametrize("col,val,expected", [
    ("imageUrl", "", True), ("image_url", "Image Url 1", True), ("photo", "", True), ("thumbnailUrl", "", True),
    ("pictureSrc", "", True), ("image", "", True),
    ("image_alt", "", False), ("photo_credit", "", False), ("photographer", "", False), ("imageCaption", "", False),
    ("thumbnailAlt", "", False), ("cover_letter", "", False), ("discoverable", "", False), ("coverage", "", False),
    ("has_image", True, False), ("photoCount", 3, False), ("photoId", "x", False), ("images", [], False),
    ("imageMeta", {}, False), ("thumbnails", ["a"], False),
])
def test_only_picture_address_columns_are_touched(col, val, expected):
    assert is_photo_column(col, val) is expected


def test_nothing_else_in_a_row_changes_and_real_values_are_kept(tmp_path):
    row = {"id": "1", "name": "Tea", "imageUrl": "https://real/x.png", "image_alt": "a cup", "photo_credit": "Bob",
           "has_image": True, "photoCount": 3, "images": [], "thumbnailUrl": "data:image/png;base64,AAAA", "photo": ""}
    p = _plan(tmp_path, rows=[row])
    fill_seed_photos(tmp_path, Fake())
    got = _rows(p)[0]
    assert got["imageUrl"] == "https://real/x.png" and got["thumbnailUrl"].startswith("data:image/png")
    for k in ("image_alt", "photo_credit", "has_image", "photoCount", "images"):
        assert got[k] == row[k], k
    assert got["photo"].startswith("https://img/")
    assert is_placeholder("Image Url 1") and not is_placeholder("https://x/y.png")


def test_the_synthesizer_leaves_a_picture_column_empty(tmp_path):
    from services.seed_synthesizer import synthesize_seed_rows
    (tmp_path / "src/db/schema").mkdir(parents=True)
    (tmp_path / "src/db/schema/menu.ts").write_text(
        'export const menuItems = pgTable("menu_items", {\n  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  name: text("name").notNull(),\n  imageUrl: text("image_url"),\n  imageAlt: text("image_alt"),\n});\n')
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps({"tables": [{"name": "menu_items", "row_count": 2}]}))
    synthesize_seed_rows(str(tmp_path))
    rows = json.loads((tmp_path / "contracts/seed-plan.json").read_text())["tables"][0]["seed_data"]
    assert all(r["imageUrl"] == "" and r["imageAlt"] != "" for r in rows)
