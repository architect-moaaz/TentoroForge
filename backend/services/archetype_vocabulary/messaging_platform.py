"""Messaging-platform vocabulary — Slack / Microsoft Teams / Discord-like
realtime team chat, DMs, threads, channel-based workspaces.

Shape mirrors the other archetype vocabs. Values are the conventions
every real messaging platform commits to (Slack, Teams, Discord,
Mattermost) that a generator would otherwise re-invent.

Design decisions worth naming:

  - **Channels + DMs + threads use card-list.** Each row is a "conversation
    tile" (name/participant + last message preview + timestamp + unread
    dot). Card-list is the shape every real messenger commits to for
    the conversation sidebar.

  - **Messages use ledger-list.** Append-only history stream —
    ledger-list keys off the timestamp column the runtime already
    surfaces.

  - **Integrations / apps use card-grid.** An app directory is browse-
    by-identity (icon + name + description).

  - **Members stays a table for admins.** Bulk provisioning /
    deactivation work; context-scoped so members don't see a members
    table.

  - **Audit log uses ledger-list.** Standard append-only history.

  - **Empty-state copy is friendly-casual** — chat tools carry a
    lighter tone than banking / clinical apps. Warmth is on-brand
    here.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


MESSAGING_PLATFORM = ArchetypeVocabulary(
    id="messaging-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Member / user — their conversations + mentions + saved items.
        "member":   ["channels", "dms", "mentions", "threads", "saved"],
        "user":     ["channels", "dms", "mentions", "threads", "saved"],

        # Workspace admin — the whole platform.
        "workspace_admin":  ["dashboard", "members", "channels",
                              "integrations", "audit-log"],
        "admin":            ["dashboard", "members", "channels",
                              "integrations", "audit-log"],

        # External / guest — limited surface: channels they're in + DMs.
        "guest":            ["channels", "dms"],
        "external_member":  ["channels", "dms"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Channels — joined / discoverable / archived.
        "channels":         ["joined", "browse-all", "archived"],

        # DMs — the universal recency + unread + muted split.
        "dms":                  ["recent", "unread", "muted"],
        "direct_messages":      ["recent", "unread", "muted"],

        # Mentions — time windows.
        "mentions":         ["today", "this-week", "all"],

        # Threads — follow / mute.
        "threads":          ["following", "muted"],

        # Integrations — installed vs. discoverable.
        "integrations":     ["installed", "available"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Channels — conversation tiles.
        "channels":         ComponentPreference(shape="card-list",
                                                 primary_field="name"),

        # Messages — append-only history stream.
        "messages":         ComponentPreference(shape="ledger-list",
                                                 primary_field="body"),

        # DMs — participant tiles.
        "dms":              ComponentPreference(shape="card-list",
                                                 primary_field="participantName"),
        "direct_messages":  ComponentPreference(shape="card-list",
                                                 primary_field="participantName"),

        # Threads — parent-message preview tiles.
        "threads":          ComponentPreference(shape="card-list",
                                                 primary_field="parentMessagePreview"),

        # Members — admin bulk-ops table.
        "members":              ComponentPreference(shape="table",
                                                     primary_field="email",
                                                     context="admin"),
        "workspace_members":    ComponentPreference(shape="table",
                                                     primary_field="email",
                                                     context="admin"),

        # Integrations / apps — the app directory grid.
        "integrations":     ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "apps":             ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Audit log — append-only ledger.
        "audit_log":        ComponentPreference(shape="ledger-list",
                                                 primary_field="action"),
        "audit_events":     ComponentPreference(shape="ledger-list",
                                                 primary_field="action"),
    },

    # ── Empty states — friendly-casual, warmth is on-brand ─────────
    signature_states={
        # Screen headliners.
        "empty_channels":       "No channels yet. Join one or start a new "
                                 "conversation.",
        "empty_dms":            "No direct messages. Start one with a "
                                 "teammate.",
        "empty_direct_messages":    "No direct messages. Start one with a "
                                     "teammate.",
        "empty_mentions":       "You're all caught up. Mentions land here "
                                 "so you don't miss them.",
        "empty_threads":        "No threads you're following. Follow one "
                                 "to keep up.",
        "empty_saved":          "Nothing saved yet. Bookmark a message to "
                                 "find it fast later.",
        "empty_integrations":   "No apps installed yet. Add one to plug "
                                 "into your workspace.",
        "empty_members":        "No members yet. Invite your team to get "
                                 "started.",
        "empty_audit_log":      "No audit events yet. Workspace changes "
                                 "will log here.",
        "empty_dashboard":      "Nothing to report yet.",

        # Per-section splits.
        "empty_joined":         "You haven't joined any channels yet.",
        "empty_browse_all":     "No public channels to browse.",
        "empty_archived":       "No archived channels.",
        "empty_recent":         "No recent conversations.",
        "empty_unread":         "No unread messages — nice.",
        "empty_muted":          "Nothing muted.",
        "empty_today":          "Nothing today.",
        "empty_this_week":      "Nothing this week yet.",
        "empty_all":            "Nothing here yet.",
        "empty_following":      "You're not following any threads.",
        "empty_installed":      "No apps installed yet.",
        "empty_available":      "No apps available — check back later.",

        # Filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Channels curation state.
        "joined":               {},
        "browse-all":           {},
        "archived":             {"status": ["archived"]},

        # DMs — visual splits (recency + unread are date/flag driven,
        # handled upstream by ordering / read-state).
        "recent":               {},
        "unread":               {},
        "muted":                {"status": ["muted"]},

        # Mentions windows — date-driven.
        "today":                {},
        "this-week":            {},
        "all":                  {},

        # Threads.
        "following":            {},

        # Integrations.
        "installed":            {"status": ["installed", "active"]},
        "available":            {"status": ["available", "not_installed"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Presence.
        "online":           {"variant": "success", "label": "Online"},
        "away":             {"variant": "warning", "label": "Away"},
        "offline":          {"variant": "neutral", "label": "Offline"},
        "dnd":              {"variant": "danger",  "label": "Do not disturb"},

        # Conversation state.
        "muted":            {"variant": "neutral", "label": "Muted"},
        "archived":         {"variant": "neutral", "label": "Archived"},

        # Member state.
        "active":           {"variant": "success", "label": "Active"},
        "deactivated":      {"variant": "neutral", "label": "Deactivated"},
        "invited":          {"variant": "warning", "label": "Invited"},

        # Integrations.
        "installed":        {"variant": "success", "label": "Installed"},
        "available":        {"variant": "neutral", "label": "Available"},
        "not_installed":    {"variant": "neutral", "label": "Not installed"},
    },

    # A dashboard in a chat product is the *admin's* screen — members
    # live in their conversations and never open it. So the tiles are
    # workspace-health questions: is the team actually here, who is
    # stuck at the door, what third-party code has access, is anyone
    # talking. Note the deliberate lack of status filters on the
    # activity tiles: in this archetype "busy", "unread" and "recent"
    # are relational or date-driven, never an enum column — inventing a
    # status here would bind to nothing.
    dashboard_recipe={
        "kpis": [
            {"label": "Active members",   "entity": "members",
             "op": "count", "filter": {"status": ["active"]}},
            {"label": "Pending invites",  "entity": "members",
             "op": "count", "filter": {"status": ["invited"]}},
            {"label": "Installed apps",   "entity": "integrations",
             "op": "count", "filter": {"status": ["installed"]}},
            {"label": "Messages sent",    "entity": "messages",
             "op": "count"},
            {"label": "Archived channels", "entity": "channels",
             "op": "count", "filter": {"status": ["archived"]}},
        ],
        "sections": [
            # Unfiltered on purpose — "most active" is an ordering the
            # runtime applies, not a state a channel is in.
            {"title": "Channels", "entity": "channels",
             "shape": "card-list", "limit": 8},

            # The one queue an admin owes somebody an action on.
            {"title": "Pending invitations", "entity": "members",
             "shape": "table", "filter": {"status": ["invited"]}, "limit": 6},

            # Workspace changes are the admin's equivalent of a message
            # feed — who added an app, who deactivated whom.
            {"title": "Recent workspace activity", "entity": "audit_log",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Reading order per screen. Conversation rows lead with the thing a
    # human recognises the conversation BY — channel name, participant,
    # the parent message — then the preview, then recency. Unread and
    # reply counts sit inline because they are the whole reason anyone
    # scans this list.
    page_recipes={
        "channels": {
            "list_columns": ["name", "purpose", "memberCount", "visibility",
                             "lastMessageAt"],
            "filter_chips": ["visibility", "status"],
            "detail_sections": [
                {"label": "Channel",  "fields": ["name", "purpose", "topic",
                                                 "visibility"]},
                {"label": "Members",  "fields": ["memberCount", "createdBy",
                                                 "createdAt"]},
                {"label": "Activity", "fields": ["messageCount", "lastMessageAt",
                                                 "status"]},
            ],
        },
        "messages": {
            "list_columns": ["body", "author", "channel", "sentAt",
                             "threadReplyCount"],
            "filter_chips": ["channel", "author"],
            "detail_sections": [
                {"label": "Message", "fields": ["body", "author", "channel"]},
                {"label": "Thread",  "fields": ["threadReplyCount",
                                                "parentMessageId", "lastReplyAt"]},
                {"label": "Meta",    "fields": ["sentAt", "editedAt",
                                                "reactionCount"]},
            ],
        },
        "dms": {
            "list_columns": ["participantName", "lastMessagePreview",
                             "unreadCount", "lastMessageAt", "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Conversation", "fields": ["participantName",
                                                     "participantEmail", "status"]},
                {"label": "Latest",       "fields": ["lastMessagePreview",
                                                     "lastMessageAt",
                                                     "unreadCount"]},
            ],
        },
        "threads": {
            "list_columns": ["parentMessagePreview", "channel", "replyCount",
                             "participantCount", "lastReplyAt"],
            "filter_chips": ["channel"],
            "detail_sections": [
                {"label": "Thread",  "fields": ["parentMessagePreview",
                                                "channel", "startedBy"]},
                {"label": "Replies", "fields": ["replyCount", "participantCount",
                                                "lastReplyAt"]},
            ],
        },
        "members": {
            "list_columns": ["email", "displayName", "role", "status",
                             "lastActiveAt", "joinedAt"],
            "filter_chips": ["role", "status"],
            "detail_sections": [
                {"label": "Profile",  "fields": ["displayName", "email",
                                                 "title", "timezone"]},
                {"label": "Access",   "fields": ["role", "status", "joinedAt",
                                                 "invitedBy"]},
                {"label": "Activity", "fields": ["lastActiveAt", "channelCount",
                                                 "messageCount"]},
            ],
        },
        "integrations": {
            "list_columns": ["name", "category", "status", "installedBy",
                             "installedAt"],
            "filter_chips": ["status", "category"],
            "detail_sections": [
                {"label": "App",     "fields": ["name", "description",
                                                "category", "publisher"]},
                {"label": "Install", "fields": ["status", "installedBy",
                                                "installedAt"]},
                {"label": "Access",  "fields": ["scopes", "channels",
                                                "webhookUrl"]},
            ],
        },
        "audit_log": {
            "list_columns": ["action", "actor", "target", "createdAt",
                             "ipAddress"],
            "filter_chips": ["action", "actor"],
            "detail_sections": [
                {"label": "Event", "fields": ["action", "target", "result",
                                              "createdAt"]},
                {"label": "Actor", "fields": ["actor", "ipAddress", "userAgent"]},
            ],
        },
    },
)
