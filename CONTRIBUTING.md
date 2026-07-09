# Contributing

Thanks for considering a contribution. This is a small, focused project — the intent is a stable, minimal MCP adapter for a self-hosted Planner backend, not a broad platform.

## Scope

The core surface is intentionally small: four tools, two transports (stdio + streamable HTTP), no authentication baked in. Additions that grow the tool set to match the Planner's evolving JSON API are welcome. Additions that duplicate what the Planner backend should do (state, caching, auth) are out of scope.

## Development

```bash
npm install
npm run build     # one-shot compile
npm run dev       # watch mode
npm run typecheck # types only, no emit
```

## Style

- Runtime type-check the tool boundary via `zod`. Internal calls are untyped where dynamism is desired.
- Keep the `stdio` code path free of any conditional imports of the HTTP transport (lazy-load it inside the `--http` branch).
- One tool = one description string in `TOOLS[]` + one case in the `CallToolRequestSchema` handler + one zod schema (if it takes arguments).

## Reporting issues

Include:
- Node version (`node --version`)
- MCP SDK version (`npm ls @modelcontextprotocol/sdk`)
- Exact command that failed
- Full stderr output

## License

By contributing, you agree that your contributions will be licensed under the MIT License in `LICENSE`.
