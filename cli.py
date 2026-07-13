"""Command-line interface for Pomavo API operations."""

import asyncio
import json
import os
import sys
from pathlib import Path

# Load environment variables from .env file if it exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from src.pomavo_mcp.client import PomavoClient


def print_json(data):
    """Pretty print JSON data."""
    if hasattr(data, "model_dump"):
        data = data.model_dump(by_alias=True)
    print(json.dumps(data, indent=2, default=str))


async def cmd_templates(client: PomavoClient, args: list[str]):
    """List templates or get a specific template."""
    if args:
        template = await client.get_template_by_name(args[0])
        if template:
            print_json(template)
        else:
            print(f"Template '{args[0]}' not found")
    else:
        templates = await client.list_templates()
        for t in templates:
            prefix = t.sequence_config.prefix if t.sequence_config else ""
            print(f"{t.id:3d} | {prefix:8s} | {t.name}")


async def cmd_projects(client: PomavoClient, args: list[str]):
    """List projects."""
    projects = await client.list_projects()
    for p in projects:
        path = await client.get_project_path(p)
        print(f"{p.id:3d} | {path:20s} | {p.name}")


async def cmd_iterations(client: PomavoClient, args: list[str]):
    """List iterations for a project."""
    if not args:
        print("Usage: iterations <project_id or slug>")
        return

    project_id = int(args[0]) if args[0].isdigit() else None
    if not project_id:
        project = await client.get_project_by_slug(args[0])
        if project:
            project_id = project.id
        else:
            print(f"Project '{args[0]}' not found")
            return

    iterations = await client.list_iterations(project_id)
    for i in iterations:
        status = "ACTIVE" if i.is_active else ("DONE" if i.is_completed else "")
        print(f"{i.id:12s} | {i.name:25s} | {status}")


async def cmd_search(client: PomavoClient, args: list[str]):
    """Search for tickets."""
    query = " ".join(args) if args else ""
    result = await client.search_tickets(query, page_size=20)
    print(f"Found {result.total_count} tickets\n")
    for item in result.items:
        title = item.fields.get("Title") or item.fields.get("title") or ""
        if len(title) > 50:
            title = title[:47] + "..."
        print(f"{item.sequence_number:12s} | {item.status:15s} | {title}")


async def cmd_get(client: PomavoClient, args: list[str]):
    """Get a ticket by sequence number."""
    if not args:
        print("Usage: get <sequence_number>")
        return

    ticket = await client.get_ticket_by_sequence(args[0])
    print(f"\n{ticket.sequence_number} - {ticket.template.name if ticket.template else 'Unknown'}")
    print(f"Status: {ticket.workflow_state.name if ticket.workflow_state else 'Unknown'}")
    print()
    for field in ticket.fields:
        label = field.template_field.label if field.template_field else field.template_field_id
        value = field.value
        if len(value) > 100:
            value = value[:97] + "..."
        print(f"  {label}: {value}")


async def cmd_create(client: PomavoClient, args: list[str]):
    """Create a new ticket.

    Usage: create <template> <title> [--project=<slug>] [--iteration=<id>] [--priority=<p>]
    """
    if len(args) < 2:
        print("Usage: create <template> <title> [--project=<slug>] [--iteration=<id>] [--priority=<p>]")
        return

    template_name = args[0]
    title_parts = []
    project = None
    iteration = None
    priority = None

    for arg in args[1:]:
        if arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg.startswith("--iteration="):
            iteration = arg.split("=", 1)[1]
        elif arg.startswith("--priority="):
            priority = arg.split("=", 1)[1]
        else:
            title_parts.append(arg)

    title = " ".join(title_parts)

    ticket = await client.create_ticket_by_template_name(
        template_name=template_name,
        title=title,
        project_slug=project,
        iteration_id=iteration,
        priority=priority,
    )

    print(f"✅ Created: {ticket.sequence_number}")
    print(f"   Template: {ticket.template.name if ticket.template else 'Unknown'}")
    print(f"   Status: {ticket.workflow_state.name if ticket.workflow_state else 'Unknown'}")


async def cmd_update(client: PomavoClient, args: list[str]):
    """Update a ticket.

    Usage: update <sequence_number> [--project=<slug>] [--iteration=<id>] [--priority=<p>]
    """
    if not args:
        print("Usage: update <sequence_number> [--project=<slug>] [--iteration=<id>] [--priority=<p>]")
        return

    sequence = args[0]
    project = None
    iteration = None
    priority = None

    for arg in args[1:]:
        if arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg.startswith("--iteration="):
            iteration = arg.split("=", 1)[1]
        elif arg.startswith("--priority="):
            priority = arg.split("=", 1)[1]

    # Get ticket to find ID and template
    ticket = await client.get_ticket_by_sequence(sequence)
    template = await client.get_template(ticket.template_id)

    field_by_label = {f.label.lower(): f.id for f in template.fields}
    fields = {}

    if project and "project" in field_by_label:
        # Convert project slug to ID if needed
        if not project.isdigit():
            project_obj = await client.get_project_by_slug(project)
            if not project_obj:
                print(f"Error: Project '{project}' not found")
                return
            project = str(project_obj.id)
        fields[field_by_label["project"]] = project
    if iteration and "iteration" in field_by_label:
        fields[field_by_label["iteration"]] = iteration
    if priority and "priority" in field_by_label:
        fields[field_by_label["priority"]] = priority

    if not fields:
        print("No updates specified")
        return

    result = await client.update_ticket(ticket.id, fields=fields)
    print(f"✅ Updated: {sequence}")
    print(f"   Response: {result}")


async def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Pomavo CLI - Interact with the Pomavo ticket system")
        print()
        print("Commands:")
        print("  templates [name]          List templates or get details")
        print("  projects                  List projects")
        print("  iterations <project>      List iterations for a project")
        print("  search [query]            Search for tickets")
        print("  get <sequence>            Get a ticket by sequence number")
        print("  create <template> <title> Create a new ticket")
        print("  update <sequence> ...     Update a ticket")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    client = PomavoClient(verify_ssl=False)

    commands = {
        "templates": cmd_templates,
        "projects": cmd_projects,
        "iterations": cmd_iterations,
        "search": cmd_search,
        "get": cmd_get,
        "create": cmd_create,
        "update": cmd_update,
    }

    if cmd in commands:
        await commands[cmd](client, args)
    else:
        print(f"Unknown command: {cmd}")
        print("Run without arguments for help")


if __name__ == "__main__":
    asyncio.run(main())
