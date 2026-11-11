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

## Sign-in

Authentication is the Cognito hosted login, authorization code flow with PKCE, using a
**public** app client (no client secret). There is no SSO and no self-service sign-up.

- Signed-out visitors see the public landing page (Stitch "Lusiform - Public Landing
  Page"). Its "Sign in" button goes to the hosted login; there is no sign-up (access is by
  invitation). The hosted login's own form should be themed to match the Stitch "Sign In"
  screen; that is Cognito configuration, done with the Cognito Terraform in `infra/`.
- The callback (`/auth/callback`) exchanges the code for tokens, which are held **in memory
  only**. Only the one-time PKCE verifier and state sit in `sessionStorage` during the
  redirect and are removed when the callback is handled. After a reload the user is signed
  out in the app; "Sign in" goes back through the hosted login, whose own session signs them
  straight back in without the password.
- API calls send `Authorization: Bearer <access token>`. A 401 triggers one refresh and a
  retry; a second 401 starts a new sign-in. A 403 (inactive user, suspended partner) shows
  an explanation.
- Roles shown in the UI come from `GET /api/me`, never from the token.

Configure with `VITE_COGNITO_DOMAIN` and `VITE_COGNITO_CLIENT_ID` (see `.env.example`).
On the app client, allow `http://localhost:5173/auth/callback` as a callback URL and
`http://localhost:5173/` as a sign-out URL. When unset, the landing page says sign-in is not
configured and its "Sign in" buttons are disabled. In Compose, the Vite dev server proxies `/api`
to the `api` service.
