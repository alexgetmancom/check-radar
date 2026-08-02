# CheckRadar

CheckRadar is a personal Telegram finance assistant. It imports receipts from the Russian Federal Tax Service and selected Gmail messages, stores a compatible SQLite data model, and exposes the bot's reports and commands.

The TypeScript application is built on the shared `typescript-boilerplate` foundation and runs on Bun.

## Status

The TypeScript implementation is the only application runtime in this repository and is the version deployed to production on VM-106. It preserves the existing SQLite schema and data while keeping the implementation and operational tooling in TypeScript.

## Features

- Telegram polling and webhook runtime modes, plus HTTP-only mode for local checks.
- Personal-user access control through `ALLOWED_USERS`.
- FNS receipt synchronization with refresh-token rotation.
- Gmail imports for Yandex Taxi, Fasten, Trytek, Timeweb, Spotify, Stripe, and OpenAI receipts.
- Legacy-compatible SQLite schema, Drizzle migrations, WAL mode, and foreign keys.
- Dashboard, weekly, monthly, food, taxi, search, backup, and receipt notifications.
- Anomaly warnings and scheduled synchronization.
- Bun tests for provider parsers, the taxi database contract, configuration, and shutdown ordering.

## Local development

1. Copy `.env.example` to `.env`.
2. Set `TELEGRAM_BOT_TOKEN` for polling mode, or use `BOT_MODE=http-only` for an HTTP-only smoke test.
3. Install dependencies:

   ```sh
   bun install
   ```

4. Apply migrations:

   ```sh
   bun run db:migrate
   ```

5. Start the application:

   ```sh
   bun run dev
   ```

The default HTTP endpoints are `http://127.0.0.1:8080/healthz` and `http://127.0.0.1:8080/readyz`.

## Commands

```sh
bun run dev          # Development server with watch mode
bun run build        # Production TypeScript build
bun run start        # Run the production build
bun run typecheck    # TypeScript validation
bun run lint         # Biome validation
bun run test         # Bun test suite
bun run check        # Lint, typecheck, tests, and build
bun run db:generate  # Generate a Drizzle migration
bun run db:migrate   # Apply migrations to DATABASE_URL
```

## Configuration

`FNS_CREDENTIALS_FILE`, `GMAIL_TOKEN_FILE`, and `GMAIL_CLIENT_SECRET_FILE` point to local secret files and are intentionally ignored by Git. `DATABASE_URL` defaults to `./data/receipts.db`.

The first migration is written to tolerate the existing SQLite tables. This allows the TypeScript process to open an existing database without recreating or deleting user data; `owner_phone` is added only when it is missing.

## Docker

Create a `.env` file with the required credentials, then run:

```sh
docker compose up -d --build
```

The container runs as the non-root `bun` user and persists SQLite data in `./data`. Compose tags the image as `check-radar:latest`; take a database backup before production deployments and keep the image versioned so a rollback remains possible.

## Repository layout

```text
src/
  bot/          Telegram handlers and application context
  db/           SQLite schema, migrations, and operations
  runtime/      Workers, shutdown, and process supervision
  services/     FNS, Gmail, reports, formatting, and notifications
  scripts/      Operational scripts
data/          Local SQLite data (ignored by Git)
tests/         TypeScript parity and foundation tests
drizzle/       Drizzle SQL migrations
```
