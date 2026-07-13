---
name: pomavo-screen-layout
description: The Pomavo layout language (layout code) for building ticket TEMPLATE SCREENS — the create form, detail view, preview pane, hover card, board card, and sidebar sections. Load this before writing a screen's layout_code. Covers the 12-column grid, every container/leaf tag (Field, Label, Plugin, Spacer, Row, Column, Section, Collapsible, Color, Font, Trigger, Text), field variants, system label types, and validation rules. For report dashboards (charts/tables) use the pomavo-report-layout skill instead.
---

# Pomavo Screen Layout (layout language)

The **layout language** (a.k.a. layout code) is a JSX-like markup that describes a ticket
**screen** for a template: the create form, detail view, preview pane, hover card, board
card, and collapsible sidebar sections. The SAME markup renders every one of those surfaces.

This skill covers the **screen** flavour (fields/labels of a ticket). The **report** flavour
(charts/tables backed by queries) shares the same grammar but a different tag set — see the
**`pomavo-report-layout`** skill for that.

## Anatomy

An element is either a **container** with children, or a self-closing **leaf**. Attribute
values come in three forms:

- **Strings** in double quotes: `id="Title"`, `align="right"`.
- **Expressions** in braces for numbers/booleans: `width={6}`, `defaultExpanded={true}`.
- **Bare booleans**, where the name alone means `true`: `mandatory` == `mandatory={true}`.

Only elements are allowed at the structural level — free text (outside `<Text>`) is a parse
error. There are no comments.

## The 12-column grid

Every screen lays out on a **12-column grid**; widths/positions are in column units.

- `width={n}` — how many of the 12 columns an element spans (`width={12}` = full width).
- Elements stack vertically by default; put them in a `<Row>` to sit side by side.
- `x` (starting column 0-11) and `y` (row 0+) place an element at an exact cell.
- At the top level, `x + width` must not exceed 12, and two positioned elements may not
  overlap the same cell.
- `height={rows}` sizes multi-line fields **in the editor**; read-only previews collapse
  height to fit content.

## Tags

**Containers** (can hold children): `Row`, `Column`, `Section`, `Collapsible`, `Color`,
`Font`, `Trigger`.
**Leaves** (must be self-closing): `Field`, `Label`, `Plugin`, `Spacer`.
**Text**: `Text` (wraps plain text between its tags).

### Field — `<Field id="..." />`
Places an editable ticket field. Requires an `id` matching a field on the template.
Attributes: `width`, `height` (multi-line), `mandatory`, `variant` (e.g. `"pills"` for
tag/dropdown fields), `heightAutoExpand` (rich-text grows with content), `align`,
`truncateLines={n}`, `showIfEmpty={false}` (hide when empty).
- `width={1}` (with default `height={1}`) renders a compact, **icon-only** field and always
  omits the label — great for dense rows and board cards.

### Label — `<Label ... />`
Renders read-only text. Two mutually-exclusive modes (never both):
- `id="FieldId"` — the field's **name/label** (not its value).
- `type="..."` — a **system label**, one of: `status`, `author`, `link-count`, `links`,
  `last-updated-relative`, `last-updated`, `created-relative`, `created`, `sequence-number`,
  `template-icon`, `template-name`.

### Plugin — `<Plugin manifestId="..." />`
Embeds a plugin-provided panel. Requires `manifestId` (stable) or `widgetId`.

### Spacer — `<Spacer width={n} />`
An empty grid cell for pushing elements apart.

### Row / Column
`<Row>` lays children horizontally, sharing the 12 columns via each child's `width`.
`<Column>` stacks children vertically within a cell. Nest them for complex layouts.

### Section — `<Section title="...">`
A titled group of fields with a legend. Purely structural grouping.

### Collapsible — `<Collapsible title="..." defaultExpanded={false}>`
An expand/collapse group. `title` is required; `defaultExpanded` controls the initial state.

### Color — `<Color ...>children</Color>`
A zero-DOM wrapper that tints its children. Exactly one source:
- `value="#rrggbb"` (or `rgb()/hsl()`), OR
- `class="primary"` (a theme color class, e.g. `primary`, `muted-foreground`), OR
- `from="field"` `id="FieldId"` (use a field's color) / `from="template"` (template color).

### Font — `<Font size="lg">children</Font>`
A zero-DOM wrapper setting the text size for its children. `size` in `xs`, `sm`, `base`,
`lg`, `xl`, `2xl`, `3xl`, `4xl`, `5xl`. Cascades via CSS inheritance.

### Trigger — `<Trigger target="preview-modal">children</Trigger>`
Wraps children so clicking them fires a behaviour. `target` currently supports
`preview-modal` (open the ticket preview).

### Text — `<Text>...</Text>`
Renders literal text between the tags. Add `renderer="markdown"` to render the content as
rich markdown (headings, lists, tables, code, links). Newlines and `${...}` inside `<Text>`
are preserved verbatim (never interpolated).

## Example

```
<Row>
  <Label type="template-icon" width={1} />
  <Font size="lg"><Label type="template-name" width={11} /></Font>
</Row>
<Field id="Title" width={12} mandatory />
<Row>
  <Field id="Priority" width={4} />
  <Field id="Assignee" width={4} />
  <Label type="status" width={4} />
</Row>
<Field id="Description" width={12} height={4} heightAutoExpand />
<Collapsible title="Details" defaultExpanded={false}>
  <Field id="Start Date" width={6} />
  <Field id="End Date" width={6} />
  <Field id="Tags" width={12} variant="pills" />
</Collapsible>
```

## Validation rules (common errors)

- `INVALID_TAG` / `INVALID_ATTRIBUTE` — unknown tag or attribute name.
- `MISSING_ID` — Field/Label/Plugin without a required id.
- `INVALID_FIELD_ID` / `INVALID_LABEL_ID` — id doesn't match a template field.
- `INVALID_LABEL_TYPE` / `CONFLICTING_LABEL_ATTRS` — bad `type`, or both `id` and `type`.
- `EXCEEDS_GRID` / `OVERLAPPING_CELLS` — root element exceeds 12 columns or overlaps.
- `INVALID_CHILDREN` — a leaf tag (Field/Label/Plugin/Spacer) was given children.
- Color: `CONFLICTING_COLOR_ATTRS`, `MISSING_COLOR_SOURCE`, `INVALID_COLOR_CLASS`.
- Font: `MISSING_FONT_SIZE`, `INVALID_FONT_SIZE`.
- Trigger: `MISSING_TRIGGER_TARGET`, `INVALID_TRIGGER_TARGET`.

## Related MCP tools & skills

- Template/screen management tools operate on a template's screens (`layout_code`).
- Related skill: **`pomavo-report-layout`** — the report flavour (charts/tables + queries).
