# Skills Center: Search / Publish / Install Reference

> Expanded reference for ms-hub §9 (Skills Center operations): category taxonomy, publishing packaging rules, installation methods, directory structure.
>
> Skills marketplace: https://www.modelscope.cn/skills

## Search Parameters

| Parameter | Type | Description |
|------|------|------|
| `search` | string | Keyword (skill name, description) |
| `filter.category` | string | Filter by category |
| `filter.developer` | string | Filter by developer |
| `filter.license` | string | Filter by license |
| `filter.custom_tag` | string | Filter by custom tag |
| `filter.owner` | string | Filter by owner |
| `page_number` / `page_size` | int | Pagination (`page_number × page_size ≤ 3000`) |

```bash
curl "$MODELSCOPE_ENDPOINT/openapi/v1/skills?search=code-review&filter.category=developer-tools&page_size=20" \
  -H "Authorization: Bearer $MODELSCOPE_API_KEY"
```

## Skill Categories (category ID)

| Category ID | Description |
|---------|------|
| `developer-tools` | Developer tools |
| `code-quality-testing` | Code quality and testing |
| `ai-media` | AI media (image/video generation, etc.) |
| `frontend-development` | Frontend development |
| `cloud-devops` | Cloud and DevOps |
| `marketing-seo` | Marketing SEO |
| `skill-management` | Skill management |
| `mobile-development` | Mobile development |
| `ai-automation` | AI automation |
| `analytics` | Data analytics |
| `doc-processing` | Document processing |
| `other` | Other |

## Response Structure

Search response `data.skills[]` entries contain: `id` (`@author/name`), `display_name`, `description`, `developer`, `category`, `tags`, `view_count`, `downloads`, `license`, `source_url`, `private`.

Details (`GET /skills/{id}`, no need to encode `@`/`/` in the id) additionally contain:

```json
{
  "install_command": [
    "npx skills add https://modelscope.cn/skills/@author/name",
    "curl -fsSL https://modelscope.cn/skills/install.sh | bash -s -- @author/name",
    "modelscope skills add @author/name"
  ],
  "locales": { "en": {"description": "...", "category": "..."}, "zh": {...} }
}
```

## Publishing a Skill (Two Steps)

### Step 1: Upload zip

```bash
curl -X POST "$MODELSCOPE_ENDPOINT/openapi/v1/files/upload" \
  -H "Authorization: Bearer $MODELSCOPE_API_KEY" \
  -F "file=@my-skill.zip" -F "type=skill"
# → Response {"data": {"id": "<uuid>"}}; use data.id as skill_file (the key is id, not file_id)
```

> The zip's root directory must contain exactly 1 `SKILL.md` file and nothing else.
> When publishing via the CLI (`ms create --repo-type skill --skill-file <zip>`), the SKILL.md frontmatter must include `name`/`version`/`description`, and the zip must be ≤ 5 MB.

### Step 2: Create the Skill

```bash
curl -X POST "$MODELSCOPE_ENDPOINT/openapi/v1/skills" \
  -H "Authorization: Bearer $MODELSCOPE_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "owner": "your-username",
    "skill_name": "my-awesome-skill",
    "display_name": "My Awesome Skill",
    "description": "Skill description",
    "skill_file": "<data.id from step 1>",
    "category": "developer-tools",
    "license": "MIT License",
    "tags": ["api-design", "automation"],
    "source_url": "https://github.com/..."
  }'
```

Field constraints: `skill_name` allows only lowercase letters, digits, and hyphens, and cannot be changed after creation; `owner` cannot be changed after creation.

## Updating a Skill

```bash
curl -X PATCH "$MODELSCOPE_ENDPOINT/openapi/v1/skills/{owner}/{skill_name}/settings" \
  -H "Authorization: Bearer $MODELSCOPE_API_KEY" -H "Content-Type: application/json" \
  -d '{"display_name": "New name", "description": "Updated description", "skill_file": "<new_file_id>", "tags": ["new-tag"]}'
```

Send only the fields you want to change; omitted fields keep their original values. Updatable: `display_name`, `description`, `skill_file`, `tags`, `source_url`, `category`, `license`. Not changeable: `owner`, `skill_name`.

## Installing a Skill

> ⚠️ `skills add` belongs to the **legacy `modelscope` CLI**; `ms` (modelscope_hub) has no `skills` subcommand. Both packages register the `ms`/`modelscope` entrypoints, and which one takes effect depends on install order—if you get "no skills command", use the curl or SDK below (most reliable).

```bash
modelscope skills add @author/skill-name                       # installs to ~/.agents/skills/ by default
modelscope skills add @author/skill-name --local_dir ./skills  # specify directory
modelscope skills add @author/skill-1 @author/skill-2          # batch
```

`modelscope skills add` parameters:

| Parameter | Description |
|------|------|
| `skill_ids` | One or more skill IDs (`@author/name`) |
| `--local_dir DIR` | Install directory (default `~/.agents/skills`) |
| `--token TOKEN` | Access Token (required for private skills) |
| `--max-workers N` | Number of concurrent downloads (default 8) |

> The legacy `modelscope` CLI's `skills` has only the `add` subcommand, no `list`/`update`/`remove`.

The most reliable installation methods (unaffected by entrypoint conflicts, from the details `install_command`):

| Method | Command | Applies to |
|------|------|------|
| curl | `curl -fsSL https://modelscope.cn/skills/install.sh \| bash -s -- <id>` | General Linux/Mac |
| SDK | `MCPApi().download_skill(skill_id="@author/name", local_dir="./skills")` (verified reliable) | Python |
| npx | `npx skills add <url>` | Node.js environment |

## Skill Directory Structure

```
my-skill/
├── SKILL.md          # required, skill definition (YAML frontmatter + Markdown instructions)
├── scripts/          # optional, utility scripts
├── references/       # optional, reference docs
└── examples/         # optional, example code
```

The SKILL.md frontmatter must include `name` and `description`:

```yaml
---
name: my-skill-name
description: >-
  A brief description of the skill. Explain when to use it and when not to.
---
```
