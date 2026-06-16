# Epic 1 Lessons Learned

This note captures the onboarding and setup issues that came up while finishing Epic 1, so Epic 2 and later work can avoid repeating them.

## What Made Setup Hard

- There were too many startup modes for too long.
- Env examples and compose behavior were not aligned at first.
- The admin access path was not obvious.
- The health check depended on persisted LedgerOS connection settings, not just container env vars.
- `make smoke` initially hid important application bootstrap logic inside an inline shell command.
- When there is no wizard, the UI still needs a dependency-aware setup order so users do not create children before parents.

## What We Should Keep Doing

- Keep one primary startup path for normal development.
- Keep the full-stack path aligned with the current LedgerOS repo and its real API routes.
- Put human-readable explanation in the README, not in commented env files.
- Keep env examples minimal and copyable.
- Put reusable setup logic in Django management commands or application code, not in Makefile shell glue.
- Make admin URLs, superuser creation, and smoke checks explicit in the docs.
- Keep smoke checks idempotent and able to recreate the stack when needed.
- Gate create screens or show a clear prerequisite path when a form depends on another record existing first.

## What To Avoid Next Time

- Avoid adding a secondary mock setup unless there is a strong, explicit reason.
- Avoid splitting the developer workflow across too many files or command variants.
- Avoid relying on stale containers when the workflow depends on new env values.
- Avoid shell one-liners for setup steps that need to survive into production or release automation.

## Epic 2 Advice

For the next epic, start by writing down:

- the single supported local setup path;
- the exact admin/user login path;
- which settings live in env vs database vs admin UI;
- what must be seeded automatically;
- what can be changed manually after boot.
- the required dependency order for any create/setup workflow without a wizard.

If a workflow step will be reused in deployment or release automation, implement it as a real command or service, not just a Make target.
