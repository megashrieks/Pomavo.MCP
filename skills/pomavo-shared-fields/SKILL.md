---
name: pomavo-shared-fields
description: Authoring Pomavo SHARED (org-level, reusable) fields via create_shared_field / update_shared_field / delete_shared_field, and attaching/detaching them to templates via add_shared_field_to_template / remove_shared_field_from_template. Covers field types, FieldOptions (select options, user multiplicity, defaults), and the force-delete rule.
---

# Pomavo Shared Fields

A **shared field** is a field definition that lives at the **org level** and can be attached to
many templates (unlike a template-local field, which belongs to a single template). Shared
fields are identified by a **GUID string** id.

- A field is *shared* when it has no owning template (`ownerTemplateId == null`).
- Template-local fields are defined inside `create_template` / the template's field collection;
  they are NOT created through these tools.

## Field shape

```json
{
  "id": "3f2c…-guid",       // GUID; assigned on create
  "label": "Severity",
  "fieldType": "dropdown",
  "fieldOptions": {
    "selectOptions": [
      { "value": "sev1", "label": "Sev 1", "icon": "flame", "color": "#e11d48" },
      { "value": "sev2", "label": "Sev 2", "color": "#f59e0b" }
    ],
    "allowMultipleUsers": false,
    "topicId": null,
    "defaultValue": null
  }
}
```

**Field types:** `text`, `number`, `textarea`, `date`, `time`, `datetime`, `checkbox`,
`dropdown`, `multiselect`, `user`.

**FieldOptions:**

- `selectOptions` — for `dropdown` / `multiselect`. Each option: `{ value, label, icon?, color? }`.
- `allowMultipleUsers` — for `user` fields, allow picking more than one user.
- `topicId` — for tag-style dynamic suggestions.
- `defaultValue` — default value string for any type.

## Tools

- **`list_shared_fields`** — list all shared fields (id, label, type).
- **`create_shared_field`** `{ label, field_type, field_options? }` — `label` and `field_type`
  are the only required inputs; the id, org, and empty FieldOptions are filled in for you.
- **`update_shared_field`** `{ field_id, label, field_type, field_options? }`.
- **`delete_shared_field`** `{ field_id, force? }` — by default this **fails if the field is
  used by any template** (returns a conflict). Pass `force: true` to detach it from every
  template first, then soft-delete it.
- **`add_shared_field_to_template`** `{ template_id, shared_field_id }` — attach the field to a
  template (409 if already attached).
- **`remove_shared_field_from_template`** `{ template_id, shared_field_id }` — detach it from a
  template (does not delete the field).

## Typical flow

1. `create_shared_field` to define the reusable field once.
2. `add_shared_field_to_template` for each template that should use it.
3. Reference it in that template's screen `layout_code` by its GUID id
   (`<Field id="3f2c…-guid" width={6} />`).
4. To retire it: `remove_shared_field_from_template` from each template (or
   `delete_shared_field` with `force: true`).
