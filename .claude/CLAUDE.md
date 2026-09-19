# CLAUDE.md

This file provides guidance and important rules working with code in this repository.

## When coding / building plan

- Use a progressive disclosure approach for agent coding in this repository: start from high-level information in the Basic Memory knowledge base, and only locate/read specific files or symbols when necessary to avoid expanding too much context at once.

## Basic Memory knowledge base (Keep context clean)

- Notes live in `memory/` (markdown with YAML frontmatter: `title`/`type`/`permalink`), tracked in git.
- Basic Memory is registered as MCP server `basic-memory`, pinned to the `cs2-vibesignatures` project (`--project cs2-vibesignatures` via project-level `.mcp.json`).
- Prefer Basic Memory MCP tools (`search_notes` / `read_note` / `write_note` / `edit_note`) for project knowledge.

## When Notes Are Insufficient (On-Demand Querying and Reading)

- Check `README.md`

## Explore SKILLs

- project-level SKILLs should be explored from `.claude/skills` even when we are using Codex.

## pages/ and shadcn/ui

`pages/` uses shadcn/ui through a hand-written `components.json` and a token
bridge in `pages/src/index.css`. Generated components live in `pages/src/ui/shadcn/`;
feature code imports the wrappers in `pages/src/ui/primitives.tsx`, which keep the
site's API and look. Only a component that composes shadcn parts itself (the
command palette: `command` + `dialog`) imports from `ui/shadcn/` directly.

- **Never run `npx shadcn init`.** It rewrites `index.css` with shadcn's values
  for `--muted` and `--accent`, which are TEXT colours here, and repaints the site.
- **Never `shadcn add --overwrite` a component that carries a local change.**
  `add` skips existing files, `--overwrite` replaces them silently. Local changes
  are marked with a `// Local change:` comment at the change; today that is
  `native-select.tsx` (`wrapperClassName`, which the sidebar language select
  needs to grow). Check with `grep -rl "Local change" pages/src/ui/shadcn` first.
- **Keep `@custom-variant dark` in `index.css`.** Without it every shadcn
  `dark:` class follows the visitor's OS theme instead of `html[data-theme]`;
  `src/theme/darkVariant.test.ts` fails if it goes.
- Restyle a shadcn component from its wrapper with classes, not by editing the
  generated file: tailwind-merge lets the wrapper's class win, and the file stays
  re-addable.
- ESLint refuses the two things this replaced: a raw `className="btn"` (use
  `<Button>`, or `buttonClass()` from `ui/buttonStyle` for a `<label>` or link)
  and `navigator.clipboard.writeText` (use `copyText()` from `ui/clipboard`,
  which toasts success or failure).
