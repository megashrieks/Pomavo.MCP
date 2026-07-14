---
name: pomavo-screen
description: The Pomavo TEMPLATE SCREEN model — what a screen is, the screen types (create, issues, edit, view, section, preview-modal, preview-pane, preview-sheet, card), how they surface in the product, and the create_screen / update_screen / delete_screen tools. For the layout code grammar itself (tags, grid, fields) load pomavo-screen-layout. Load this before create_screen / update_screen.
---

# Pomavo Template Screens

A **screen** belongs to a template and pairs a **name** (its type) with **layout code** — the
JSX-like markup that renders a surface of a ticket. One template has many screens; each screen
is one surface (the create form, the detail view, a sidebar section, a preview, etc.).

> This skill covers the screen **types** and how they are used. For the layout **language**
> (the grid, `<Field>`, `<Row>`, `<Section>`, labels, etc.) load the **`pomavo-screen-layout`**
> skill and use it to write each screen's `layout_code`.

## Screen shape

```json
{
  "id": 12,                    // present on existing screens; used to target update/delete
  "name": "create",           // the screen TYPE (see table)
  "description": "Create form",
  "layoutCode": "<Row>...</Row>",
  "sortOrder": 0               // only meaningful for "section" screens
}
```

## Screen types (the `name` field)

There is no strict enum — the `name` string identifies the type. The types the product renders:

| `name` | Where it shows | Notes |
|--------|----------------|-------|
| `create` | The "new ticket" form | Author field NOT allowed here. |
| `issues` | List / board item view | Author field NOT allowed here. |
| `edit` | The edit form | Author field NOT allowed here. |
| `view` | Detail view body | Typically read-only. |
| `section` | A collapsible section in the detail sidebar | Uses `sortOrder` (lower = higher). Author field allowed. |
| `preview-modal` | Full-screen preview modal | Opened via a `<Trigger target="preview-modal">`. Author allowed. |
| `preview-pane` | Side preview pane | Author allowed. |
| `preview-sheet` | Slide-over sheet / drawer preview | Compact detail. Author allowed. |
| `card` | Card / list-item rendering | Compact. |

### Author-field rule

The template's **Author** field may only appear on `section` and `preview-*` screens. Putting
it on `create`, `edit`, or `issues` is a validation error
(`AUTHOR_FIELD_NOT_ALLOWED_ON_SCREEN`).

### sortOrder

`sortOrder` only affects `section` screens — it orders the collapsible sections in the detail
sidebar (lower values first). Ignore it for other types.

## The tools (fetch-mutate-save)

There are no per-screen backend endpoints; screens live inside the template's screen
collection. The tools handle that for you:

- **`create_screen`** `{ template_id, name, description, layout_code?, sort_order? }` — appends
  a screen.
- **`update_screen`** `{ template_id, screen_id? | name?, description?, layout_code?,
  sort_order? }` — edits ONE screen (identify by `screen_id` or by `name`); only the fields you
  pass change.
- **`delete_screen`** `{ template_id, screen_id? | name? }` — removes ONE screen.

Each tool fetches the template, mutates the single screen, and saves the whole collection —
so concurrent screens are preserved.

## Writing layout_code

`layout_code` references the template's field `id`s (e.g. `<Field id="priority" width={6} />`).
Load **`pomavo-screen-layout`** for the full grammar: the 12-column grid; containers
(`Row`, `Column`, `Section`, `Collapsible`, `Color`, `Font`, `Trigger`); leaves (`Field`,
`Label`, `Plugin`, `Spacer`, `Text`); field variants; and system label types. A referenced
field id that doesn't exist on the template is a validation error (`INVALID_FIELD_ID`).

Note: charts/tables (`RadialChart`, `BarChart`, `Table`, …) belong to **report** layouts, not
template screens — use the **`pomavo-report-layout`** skill for those.

## Authoring best practices

Guidance for producing screens that look good in the product (not hard validation rules):

- **Don't add the ticket title/name to any screen.** The title is rendered implicitly outside
  the screen space (in the header/chrome), so including a `title` field or `template-name`
  label inside the layout duplicates it.
- **Don't put the `status` label in the issue body** (`create`/`edit`/`view`/`issues`). Status
  is already shown outside the screen space, so a `<Label type="status" />` in the body is
  redundant.
- **Don't over-group.** You don't need to wrap fields in a `<Section>` or `<Collapsible>` every
  time — only group when the fields naturally belong together. A flat set of `<Row>`s is often
  cleaner.
- **`section` screens: avoid `<Section>`/`<Collapsible>` inside them.** Sidebar sections are
  already small, collapsible groups — nesting another section/collapsible inside is redundant
  and looks cluttered. Put the fields directly in the layout.
- **The `section` screen's own name/description is the visible section title.** In the sidebar
  the section screen's name already renders as the header, so don't add a separate `<Section>`
  title inside for the same purpose. Keep that section name short too (long ones overflow).
- **Include a project + iteration `section`** in the sidebar so users can change them when
  needed. These are commonly-adjusted fields and belong in the always-visible sidebar.
- **Keep section / collapsible titles short.** Long titles overflow the header and ruin the
  look — prefer terse labels (e.g. "Location", not a full sentence describing the group).
- **Prefer rich text over plain textarea when possible.** A rich-text field captures a wider
  variety of content (formatting, lists, links, embeds), so favour it for descriptive/free-form
  fields unless a plain single-style textarea is specifically required.
- **Give dropdown options an icon and color.** Dropdown/select options render their `icon` and
  `color` in the UI — populating them (on the field's `selectOptions`) makes the screen far more
  readable and visually scannable. Prefer configuring them.
