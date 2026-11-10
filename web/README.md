# web

The consultant and admin UI: React with Vite, TypeScript, shadcn/ui, and
Tailwind CSS.

- Screens, components, and client state belong here.
- UI numbers come from the estimate service, never from model text.
- Packages are managed with `pnpm`; run everything through Docker Compose (see
  `.kiro/steering/docker.md`).

## Toolchain

Node 22 (`node:22-alpine`), pnpm 12.18.0, Vite 8, React 19, TypeScript 5.9,
Tailwind CSS 4 (via `@tailwindcss/vite`), shadcn/ui (`components.json`, new-york
style), ESLint 10 (flat config), Vitest 5 with jsdom and Testing Library. All
versions are pinned exactly in `package.json` and locked in `pnpm-lock.yaml`.

Design tokens from the Stitch project live in `src/index.css`: primary
`#0f766e`, Inter for sans, JetBrains Mono for mono, and 8px (`rounded-md`) /
12px (`rounded-lg`) radii.

## Commands (single-run)

Compose lands in task 1.5; once it does, run:

```
docker compose run --rm web pnpm lint
docker compose run --rm web pnpm test --run
docker compose run --rm web pnpm build
docker compose run --rm web pnpm typecheck
docker compose run --rm web pnpm add -E <pkg>
```

Before compose exists, the same scripts run in a throwaway container:

```
docker run --rm -v "$PWD/web":/app -v lusiform_web_nm:/app/node_modules -w /app \
  node:22-alpine sh -c "npm i -g pnpm@12.18.0 && pnpm install --frozen-lockfile && pnpm lint && pnpm test --run && pnpm build"
```
