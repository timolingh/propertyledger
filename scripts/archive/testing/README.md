# Archived testing shell scripts

Archived November 24, 2026. These scripts support the historical beta/demo environment and are not production setup commands.

| Script | Purpose |
| --- | --- |
| `beta-reset.sh` | Deletes the PropertyLedger and sibling LedgerOS local Docker volumes. |
| `beta-seed.sh` | Prepares sample LedgerOS books and synthetic PropertyLedger demo records/users. |
| `workflow-test-status.sh` | Reads workflow fixture status and release compatibility inventory. |

The scripts retain their executable permissions and resolve the repository root from this directory. Commands in the [archived testing guides](../../../docs/archive/testing/README.md) assume the current directory is the repository root.

Historical setup instructions are in the archived [Quick Start Guide](../../../docs/archive/manuals/quick-start.md) and [Admin Setup Guide](../../../docs/archive/manuals/admin-setup.md). The development bootstrap remains at `scripts/dev-bootstrap.sh`; release checks remain in the Makefile.
