# WP1 browser acceptance

These screenshots use fictional records exported from an isolated disposable test database, with LedgerOS health stubbed. They demonstrate UI behavior, not live accounting posting or LedgerOS availability.

- [Desktop home](desktop.png)
- [Mobile home](mobile.png)
- [Mobile navigation drawer](mobile-menu.png)
- [Existing property list](records.png)
- [Read-only home](viewer.png)
- [LedgerOS outage](outage.png)

Reproduce from the repository root:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py shell -c "exec(open('scripts/export-workflow-preview.py').read())"
node scripts/check-workflow-ui.mjs docs/qa/wp1
```

The exporter creates and destroys a separate `test_propertyledger_workflow_preview` database. It does not change the application database or send LedgerOS requests. The browser check requires Node and a local Chrome executable; set `CHROME_PATH` if Chrome is installed outside the script's default macOS application location. These are optional developer QA tools, not runtime dependencies. Exported HTML and copied assets are ignored by Git.

Verified in headless Chrome at 1440×1000 and 390×844: three cards, no horizontal page overflow, desktop collapse and remembered preference, closed mobile navigation excluded from focus, drawer modal semantics, initial focus, Tab/Shift+Tab containment, Escape and focus return, existing record navigation active state, viewer actions, and an outage message. Sidebar and content are also usable without JavaScript: mobile navigation stays expanded above the page.

Not exercised here: screen-reader testing, production static hosting, a real LedgerOS outage, or financial posting. Those remain integration/release checks.
