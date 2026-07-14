---
name: pomavo-template
description: Authoring Pomavo ticket TEMPLATES (issue types like Bug, Task, Epic) via create_template / update_template. Covers the mandatory fields every template must define (Title, Description, Author, Assignee), the field types and FieldOptions, the screen collection, the workflow requirement (existing or inline), and the optional sequence (ticket-ID) config. Load this before create_template.
---

# Pomavo Template Authoring

A **template** is an issue-type definition. It bundles: a set of **fields**, one or more
**screens** (layout code), a **workflow** (state machine), and a **sequence config**
(ticket-ID prefix). Templates are **org-scoped** and their name must be unique in the org.

## create_template — what you must supply

| Arg | Required | Notes |
|-----|----------|-------|
| `name` | yes | Unique within the org. |
| `description` | yes | Free text. |
| `icon` | yes | Lucide icon name, e.g. `bug`, `check-square`, `layers`. |
| `color` | yes | Hex string, e.g. `#e11d48`. |
| `fields` | yes | Array of field defs — MUST include the 4 mandatory fields below. |
| `screens` | yes | Array of screen defs — at least one. |
| `workflow_id` **or** `workflow` | yes (one of) | Existing workflow id, or an inline new workflow. |
| `sequence_config` | **yes** | `{ prefix, suffix, minimumDigits }`. Required — a template without it cannot mint ticket IDs and ticket creation will fail. |

## Mandatory fields (validation will reject the template without these)

Every template MUST define fields with these exact labels:

- **`Title`** — typically `text`.
- **`Description`** — typically `textarea`.
- **`Author`** — `fieldType` MUST be `user`.
- **`Assignee`** — `fieldType` MUST be `user`.

The **Author** field may only appear on `section` and `preview-*` screens — never on
`create`, `edit`, or `issues` screens (validation error `AUTHOR_FIELD_NOT_ALLOWED_ON_SCREEN`).

## Field definition

```json
{
  "id": "optional-guid",          // auto-generated if omitted; screens reference this id
  "label": "Priority",
  "fieldType": "dropdown",
  "fieldOptions": {                 // optional
    "selectOptions": [
      { "value": "high", "label": "High", "icon": "arrow-up", "color": "#e11d48" },
      { "value": "low",  "label": "Low",  "color": "#22c55e" }
    ],
    "allowMultipleUsers": false,    // for user fields
    "topicId": null,                 // for tag-style fields
    "defaultValue": null
  }
}
```

**Field types:** `text`, `number`, `textarea`, `date`, `time`, `datetime`, `checkbox`,
`dropdown`, `multiselect`, `user`.

- `selectOptions` is only meaningful for `dropdown` / `multiselect`.
- `allowMultipleUsers` is only meaningful for `user`.
- If you omit `id`, a GUID is generated — but then you must reference fields in screen
  layout code by that generated id, so it is usually easier to supply your own ids.

## Screens

Provide at least one screen. Each screen: `{ name, description, layoutCode?, sortOrder? }`.
Screen `layoutCode` references field `id`s. See the **`pomavo-screen`** skill for the screen
types and the **`pomavo-screen-layout`** skill for the layout language.

A minimal template usually ships a `create` screen and one or more `section` / `preview-*`
screens. `layoutCode` may be an empty string.

## Workflow (required)

A template needs a workflow. Either:

- **Reference an existing one:** pass `workflow_id` (use `list_workflows` to find it).
- **Create inline:** pass a `workflow` object `{ name, description, states, transitions }`.

Either way the workflow MUST contain a state with `category: "initial"` **named exactly
`Created`**. See the **`pomavo-workflow`** skill for state/transition shape and categories.

## Sequence config (required)

`{ "prefix": "TASK", "suffix": "", "minimumDigits": 4 }` → generates `TASK-0001`, `TASK-0002`.

- **Required.** A template created without a sequence config cannot generate ticket IDs, and
  ticket creation will fail with `SEQUENCE_CONFIG_REQUIRED`. Always supply one.
- `prefix` must be non-empty, unique in the org, and must NOT end with a digit.
- `minimumDigits` is 1–10.

## Editing an existing template

- **`update_template`** — change `name`/`description`/`icon`/`color` only.
- **`update_template_workflow`** — point the template at a different workflow.
- **Screens** — use `create_screen` / `update_screen` / `delete_screen` (they fetch the
  template, mutate the one screen, and save the collection).
- **Shared fields** — attach a reusable org-level field with `add_shared_field_to_template`
  (see the **`pomavo-shared-fields`** skill).
- **`delete_template`** — soft-deletes the template.

## Example (compact)

```json
{
  "name": "Bug",
  "description": "Something is broken",
  "icon": "bug",
  "color": "#e11d48",
  "fields": [
    { "id": "title", "label": "Title", "fieldType": "text" },
    { "id": "desc", "label": "Description", "fieldType": "textarea" },
    { "id": "author", "label": "Author", "fieldType": "user" },
    { "id": "assignee", "label": "Assignee", "fieldType": "user" },
    { "id": "priority", "label": "Priority", "fieldType": "dropdown",
      "fieldOptions": { "selectOptions": [
        { "value": "high", "label": "High", "color": "#e11d48" },
        { "value": "low",  "label": "Low",  "color": "#22c55e" } ] } }
  ],
  "screens": [
    { "name": "create", "description": "Create form",
      "layoutCode": "<Row><Field id=\"title\" width={12} mandatory /></Row><Row><Field id=\"desc\" width={12} /></Row><Row><Field id=\"priority\" width={6} /><Field id=\"assignee\" width={6} /></Row>" }
  ],
  "workflow": {
    "name": "Bug flow", "description": "Bug lifecycle",
    "states": [
      { "id": "s-created", "name": "Created", "description": "New", "category": "initial", "color": "#64748b", "graphData": "{}" },
      { "id": "s-done",    "name": "Done",    "description": "Fixed", "category": "terminal", "color": "#22c55e", "graphData": "{}" }
    ],
    "transitions": [
      { "name": "Resolve", "description": "Mark fixed", "fromStateId": "s-created", "toStateId": "s-done" }
    ]
  },
  "sequence_config": { "prefix": "BUG", "suffix": "", "minimumDigits": 4 }
}
```
