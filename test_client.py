"""Simple test script for the Pomavo API client."""

import asyncio
import os

# Load environment variables from .env file if it exists
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from src.pomavo_mcp.client import PomavoClient


async def main():
    """Test the Pomavo API client."""
    # Create client (will read from environment variables)
    client = PomavoClient(verify_ssl=False)

    print("=" * 50)
    print("Testing Pomavo API Client")
    print("=" * 50)

    # List templates
    print("\n📋 Templates:")
    templates = await client.list_templates()
    for t in templates:
        prefix = t.sequence_config.prefix if t.sequence_config else ""
        print(f"  - {t.name} (ID: {t.id}, Prefix: {prefix})")

    # List projects
    print("\n📁 Projects:")
    projects = await client.list_projects()
    for p in projects:
        path = await client.get_project_path(p)
        print(f"  - {p.name} (ID: {p.id}, Slug: {path})")

    # Get active iteration for first child project
    child_projects = [p for p in projects if p.parent_project_id is not None]
    if child_projects:
        project = child_projects[0]
        print(f"\n⏱️ Iterations for {project.name}:")
        iterations = await client.list_iterations(project.id)
        for i in iterations:
            status = "✅ ACTIVE" if i.is_active else ("✓ Done" if i.is_completed else "")
            print(f"  - {i.name} (ID: {i.id}) {status}")

    # Search for recent tickets
    print("\n🔍 Recent Tickets:")
    result = await client.search_tickets(page_size=5)
    print(f"  Total: {result.total_count} tickets")
    for item in result.items:
        title = item.fields.get("Title") or item.fields.get("title") or "No title"
        print(f"  - {item.sequence_number}: {title} [{item.status}]")

    # Get a specific template's fields
    bug_template = await client.get_template_by_name("Bug Report")
    if bug_template:
        print(f"\n🐛 Bug Report Template Fields:")
        for field in bug_template.fields:
            print(f"  - {field.label} ({field.field_type}) - ID: {field.id}")

    print("\n" + "=" * 50)
    print("✅ All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
