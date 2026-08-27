# Archetype vocabulary recipes — authoring spec

Two new fields on `ArchetypeVocabulary`. Both are hand-authored domain
knowledge; both are resolved against the app's real registry at
generation time, so a name the app lacks is dropped, never invented.

## 1. `dashboard_recipe` — what this industry opens the app to see

```python
dashboard_recipe={
    "kpis": [
        {"label": "Low stock", "entity": "products", "op": "count",
         "filter": {"status": ["low_stock", "lowstock", "reorder"]}},
        {"label": "Inventory value", "entity": "products", "op": "sum",
         "field": "price"},
    ],
    "sections": [
        {"title": "Needs reordering", "entity": "products", "shape": "table",
         "filter": {"status": ["low_stock", "reorder"]}, "limit": 8},
        {"title": "Recent stock movements", "entity": "stock_movements",
         "shape": "ledger-list", "limit": 10},
    ],
},
```

- `op` ∈ `count` | `sum` | `avg`. `sum`/`avg` REQUIRE `field`.
- `filter` values are a **list of candidate spellings**, most-preferred
  first. The app's declared enum picks the winner; if none match, the
  KPI is dropped and the section renders unfiltered. This is why
  candidates matter — one app says `low_stock`, the next `reorder`.
- `shape` ∈ table | card-list | card-grid | schedule-grid | ledger-list | kanban.
- Author **4-6 KPIs** and **3 sections**, in priority order.

## 2. `page_recipes` — what an entity's screens SHOW

```python
page_recipes={
    "products": {
        "list_columns": ["sku", "name", "status", "quantityOnHand", "reorderPoint"],
        "filter_chips": ["status", "category"],
        "detail_sections": [
            {"label": "Item",     "fields": ["sku", "name", "category", "description"]},
            {"label": "Stock",    "fields": ["quantityOnHand", "reorderPoint", "warehouse"]},
            {"label": "Supplier", "fields": ["supplier", "leadTimeDays", "unitCost"]},
        ],
    },
}
```

- `list_columns`: **4-6**, the domain's reading order, most identifying
  first. Never lead with `id` or a timestamp.
- `detail_sections`: 2-4 groups a person in this job would recognise.
- Column names: use the single most conventional camelCase domain name.
  Matching ignores case and underscores, so `quantity_on_hand` finds
  `quantityOnHand` — do not list aliases.
- Cover the vocabulary's **6-10 most important entities**, not all of them.

## Hard rules (enforced by `tests/services/test_vocabulary_recipes.py`)

1. Every `entity` in either recipe MUST be a key in that same file's
   `component_preferences`.
2. Every status-column filter value MUST appear in that same file's
   `status_badges`.
3. `list_columns` ≤ 7, no duplicates, non-empty.
4. Every `detail_sections` entry needs both `label` and `fields`.
5. `signature_states` must carry `empty_dashboard`.

Rules 1 and 2 exist because a recipe that names something the
vocabulary doesn't declare binds to nothing and fails silently — the
page just quietly falls back to generic, which is the exact defect this
layer was built to remove.
