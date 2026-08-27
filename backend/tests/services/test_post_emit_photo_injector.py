"""Tests for the post-emit photo injector."""
from __future__ import annotations
import copy
from services.post_emit_photo_injector import inject_photos


_ENTITY_PHOTOS = {
    "User": "https://picsum.photos/seed/user-x/1600/900",
    "Note": "https://picsum.photos/seed/note-x/1600/900",
}


def test_avatar_in_repeat_gets_photourl():
    """Avatar inside a Repeat<User> should get photoUrl = entityPhotos.User."""
    page = {
        "schemaVersion": 2, "id": "users", "route": "/users",
        "root": {
            "type": "Stack", "id": "stack-1", "children": [
                {
                    "type": "Repeat", "id": "rep-1",
                    "props": {"each": "users", "entity": "User"},
                    "children": [
                        {"type": "Avatar", "id": "av-1", "props": {"name": "{{item.name}}"}},
                    ]
                }
            ]
        },
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    avatar = out["root"]["children"][0]["children"][0]
    assert avatar["props"]["photoUrl"] == _ENTITY_PHOTOS["User"]


def test_avatar_without_repeat_context_uses_first_entity():
    """A bare Avatar (no enclosing Repeat) falls back to the first entityPhotos entry."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {
            "type": "Stack", "id": "s",
            "children": [{"type": "Avatar", "id": "a", "props": {"name": "Me"}}]
        }
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    photo = out["root"]["children"][0]["props"]["photoUrl"]
    assert photo in _ENTITY_PHOTOS.values()


def test_avatar_with_existing_photourl_is_not_overwritten():
    """If the LLM already set photoUrl, don't clobber it."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {
            "type": "Avatar", "id": "a",
            "props": {"name": "Me", "photoUrl": "https://existing.example.com/a.jpg"}
        }
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    assert out["root"]["props"]["photoUrl"] == "https://existing.example.com/a.jpg"


def test_hero_gets_background_image():
    """A Hero without backgroundImage gets one set from entityPhotos."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {
            "type": "Hero", "id": "h",
            "props": {"title": "Welcome"}
        }
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    bg = out["root"]["props"].get("backgroundImage")
    assert bg is not None
    assert bg["url"] in _ENTITY_PHOTOS.values()
    assert 0 <= bg["overlay"] <= 1


def test_hero_with_existing_background_image_preserved():
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {
            "type": "Hero", "id": "h",
            "props": {"title": "Welcome", "backgroundImage": {"url": "https://x.com/y.jpg", "overlay": 0.3}}
        }
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    assert out["root"]["props"]["backgroundImage"]["url"] == "https://x.com/y.jpg"


def test_no_entity_photos_is_noop():
    """Empty entityPhotos → page passes through unchanged."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {"type": "Avatar", "id": "a", "props": {"name": "x"}}
    }
    out = inject_photos(copy.deepcopy(page), {})
    assert out == page


def test_walks_deeply_nested_trees():
    """Recursion goes through children at any depth."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {"type": "Stack", "id": "s1", "children": [
            {"type": "Stack", "id": "s2", "children": [
                {"type": "Stack", "id": "s3", "children": [
                    {"type": "Avatar", "id": "a", "props": {"name": "x"}}
                ]}
            ]}
        ]}
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    avatar = out["root"]["children"][0]["children"][0]["children"][0]
    assert "photoUrl" in avatar["props"]


def test_handles_slots_in_addition_to_children():
    """Some nodes use 'slots' (named slots) instead of 'children'."""
    page = {
        "schemaVersion": 2, "id": "p", "route": "/",
        "root": {
            "type": "Section", "id": "sec",
            "slots": {
                "header": [{"type": "Hero", "id": "h", "props": {"title": "x"}}],
            }
        }
    }
    out = inject_photos(copy.deepcopy(page), _ENTITY_PHOTOS)
    hero = out["root"]["slots"]["header"][0]
    assert hero["props"].get("backgroundImage") is not None
