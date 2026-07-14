---
name: pomavo-template-link
description: Authoring Pomavo TEMPLATE LINK types (the configurable relationship types like Blocks, Relates to, Parent of) via create_template_link / update_template_link / delete_template_link. Covers the name plus the outward/inward direction names.
---

# Pomavo Template Links (relationship types)

A **template link** defines a *type* of relationship that can exist between two tickets
(e.g. "Blocks", "Relates to", "Duplicates"). It is org-scoped and its `name` must be unique in
the org. Actual ticket-to-ticket links (created with `link_tickets`) reference one of these
types by id.

## Fields

| Field | Meaning | Example |
|-------|---------|---------|
| `name` | The relationship's canonical name (unique in org). | `Blocks` |
| `outward_name` | Reading FROM the source ticket. | `blocks` |
| `inward_name` | Reading FROM the target ticket. | `is blocked by` |

So if ticket A links to ticket B with this type: **A `blocks` B**, and from B's side,
**B `is blocked by` A**.

## Tools

- **`list_template_links`** — see existing types and their ids.
- **`create_template_link`** `{ name, outward_name, inward_name }`.
- **`update_template_link`** `{ link_id, name, outward_name, inward_name }` — all four required.
- **`delete_template_link`** `{ link_id }`.

## Examples

| name | outward_name | inward_name |
|------|--------------|-------------|
| Blocks | blocks | is blocked by |
| Relates to | relates to | relates to |
| Duplicates | duplicates | is duplicated by |
| Parent of | is parent of | is child of |
| Causes | causes | is caused by |

For symmetric relationships (like "Relates to"), set `outward_name` and `inward_name` to the
same phrase.

All three text fields are required and must be non-empty. Creating or renaming to a `name`
that already exists in the org fails with `LINK_NAME_EXISTS`.
