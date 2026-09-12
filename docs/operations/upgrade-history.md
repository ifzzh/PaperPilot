# Historical upgrade procedures

Archived from the pre-iPaper README on 2026-09-11. These are version-specific historical instructions, not the current deployment recipe. Worker repositories have since moved to `ifzzh520/paperpilot-translation-worker` and `ifzzh520/paperpilot-document-worker`; preserve component versions and verify migrated digests before using older examples. Do not restore an old database over new writes.

### Upgrading from v0.8.2

v0.9.0 replaces Supabase with local accounts and introduces complete tenant ownership. Stop v0.8.2 and back up both SQLite and the paper tree before continuing. Create the bootstrap administrator first, then preview and apply the offline migration:

```bash
python -m paperpilot.auth_cli --db /app/db/paperpilot.db create-admin --username ifzzh
python -m paperpilot.migrations.tenant_storage --db /app/db/paperpilot.db \
  --papers-root /data/papers --owner ifzzh --dry-run
python -m paperpilot.migrations.tenant_storage --db /app/db/paperpilot.db \
  --papers-root /data/papers --owner ifzzh \
  --key-file /run/secrets/paperpilot_settings_key \
  --backup-dir /backups --apply
```

The password prompts are hidden; never put a password in shell history. Existing records and files are assigned to `ifzzh` and moved under `.users/<user-uuid>/`. The generated manifest supports `--rollback <manifest>`. After deployment, public HTTPS AI Providers can be approved immediately from the administrator page; private targets remain deployment-only.

### Upgrading from v0.9.1

v0.10.0 adds a persistent per-user translation task center with structured progress, pause/resume/retry and seven-day task-local cache recovery. It also defaults the UI to Simplified Chinese and `YYYY-MM-DD`, provides self-service password changes with an 8-character minimum, and configures personalized Daily arXiv topics with a daily maximum of 24 papers retained for seven arXiv release dates.

v0.10.5 fixes Translation Worker subprocess imports when BabelDOC runs from a task working directory and lets paper cards open the latest persisted task log after completion or failure. Existing failed tasks remain visible and require an explicit manual retry. Releases now publish only changed component images while scanning and recording the complete compatible deployment matrix.

v0.11.0 self-hosts Marked, Highlight.js, MathJax, Font Awesome and DOMPurify, removes dormant browser PDF parsing, and enforces a blocking Content Security Policy with `script-src 'self'` and `script-src-attr 'none'`. No database or paper migration is required. Only the Web image changes; keep the pinned v0.10.5 Translation Worker and v0.10.4 Document Worker digests listed in `docker/release-components.json`. Inline styles remain temporarily allowed for visual compatibility and are scheduled for v0.11.1.

For an installation already on v0.10.2, stop all services, back up SQLite and the paper directory, then run `python -m paperpilot.migrations.v0103_daily_assets --db /path/to/paperpilot.db --dry-run` followed by `--apply --backup-dir /path/to/backups`, as documented in [the v0.10.4 release notes](../releases/v0.10.4.md). The migration adds persistent Daily arXiv asset leases and requeues unfinished candidates without rerunning LLM enrichment or moving PDFs. Deploy all three v0.10.4 image digests together. Rollback restores the migration manifest backup and all three v0.10.2 image digests.

### Upgrading from v0.9.0

v0.9.1 restores tenant Reading List discovery, lowers the password minimum to 8 characters, and supports transparent DNS proxy fake-IP ranges without allowing private Providers. If your resolver maps public names into RFC 2544 addresses, set `PAPERPILOT_AI_PROXY_FAKE_IP_RANGES=198.18.0.0/15` once in the deployment environment. The exception applies only to approved HTTPS hostnames; IP literals and LAN targets remain forbidden. No database or file migration is required.

### Upgrading from v0.7.0

v0.8.0 replaces the Flask development server in production with Gunicorn, bounds analysis/export/Daily arXiv queues, and upgrades the supported runtime dependencies. Upload and document-processing APIs remain unchanged. `GET /api/papers-dir` now returns `{"success": true, "storage": "managed"}` instead of an absolute server path, and the export page displays “服务器托管存储”.

There is no database or storage migration. Back up SQLite, update all three image digests together, and verify `/healthz`, `/readyz`, an eight-request concurrency probe, and graceful SIGTERM. Rollback only requires restoring the three v0.7.0 image digests. The release gate is available locally as `./scripts/security_scan.sh`; it pins pip-audit 2.10.1 and Trivy 0.74.0, creates CycloneDX SBOMs, and rejects fixable HIGH/CRITICAL findings unless a specific, expiring exception is documented.

### Upgrading from v0.6.0

v0.7.0 makes PDF uploads asynchronous and validates PDFs, metadata ZIPs, Zotero RDF, and MinerU result ZIPs in an isolated Document Worker. PDF files are limited to 100 MiB; archives are limited to 200 MiB compressed, 2 GiB expanded, 2,000 entries, and 500 paper records. Existing v0.3–v0.6 metadata-only exports remain supported, but archives containing PDFs or unknown attachments are rejected.

Create the separate Document Worker token shown above, then update all three image digests together. The additive `document_jobs` table is created automatically and requires no storage migration. The Compose file keeps `7191` bound to localhost, gives the Web service 3 CPU/3 GiB/256 PID, and gives the Document Worker 2 CPU/3 GiB/128 PID with a 3 GiB ephemeral tmpfs. Rollback consists of stopping v0.7.0, pinning the Web and translation Worker to v0.6.0 digests, and removing the Document Worker; the additional table may remain.

### Upgrading from v0.5.0

v0.6.0 makes AI credentials write-only in the browser and encrypts them in SQLite with the separate settings key. Stop PaperPilot before upgrading. Generate and securely back up `paperpilot-settings.key`, then inspect and apply the offline migration using the v0.6.0 Web image or an equivalent source checkout:

```bash
python -m paperpilot.migrations.agentic_secrets \
  --db /app/db/paperpilot.db --dry-run
python -m paperpilot.migrations.agentic_secrets \
  --db /app/db/paperpilot.db \
  --key-file /run/secrets/paperpilot_settings_key \
  --backup-dir /backups --apply
```

The generated manifest contains no credentials and supports `--rollback <manifest>`. Keep the pre-migration database backup protected because it may contain old plaintext credentials. Losing the settings key makes encrypted credentials unrecoverable.

Every configurable LLM or local MinerU origin must be listed exactly in `PAPERPILOT_AI_ALLOWED_ORIGINS` or `PAPERPILOT_AI_PRIVATE_ALLOWED_ORIGINS`. MinerU pre-signed storage origins use `PAPERPILOT_MINERU_TRANSFER_ALLOWED_ORIGINS`. Public origins require HTTPS; private HTTP is allowed only for an exact explicitly approved origin. Redirects, loopback, link-local and cloud-metadata targets are rejected.

### Upgrading from v0.4.0

v0.5.0 removes stored-XSS paths in paper, category, chat, analysis, settings and Daily arXiv rendering. Normal text keeps the existing layout but is no longer interpreted as HTML. AI chat and analysis still support Markdown headings, lists, tables, quotes, highlighted code and MathJax formulas; rendered HTML is cleaned by the self-hosted, pinned DOMPurify 3.4.14 build. External Markdown images are shown as HTTPS links instead of loading automatically, while controlled same-origin analysis images continue to display.

There is no database or storage migration. Update both Web and Worker image tags together. Browser security headers are added on every response; CSP is intentionally Report-Only in this release so existing inline handlers and pinned CDN assets remain functional. To roll back, pin both images to their v0.4.0 digests.

### Upgrading from v0.3.0

v0.4.0 moves BabelDOC into an isolated Worker and upgrades it to 0.6.4. There is no paper-storage migration. Add the staging mount, Worker token, and Worker service shown in `docker-compose.yaml`, then start both services. The additive `translation_jobs` table is created automatically. To roll back, stop both services and pin the Web image back to the v0.3.0 digest; the extra table is backward compatible.

### Upgrading from v0.2.0

v0.3.0 stores category files in deterministic ID directories under
`/data/papers/.categories/`. Stop PaperPilot before migrating, then run:

```bash
python -m paperpilot.migrations.category_storage \
  --papers-dir /data/papers --db /app/db/paperpilot.db --dry-run
python -m paperpilot.migrations.category_storage \
  --papers-dir /data/papers --db /app/db/paperpilot.db \
  --backup-dir /backups --apply
```

Keep the printed manifest path. To roll back while the service is stopped:

```bash
python -m paperpilot.migrations.category_storage \
  --papers-dir /data/papers --db /app/db/paperpilot.db \
  --rollback /data/papers/.paperpilot-migrations/<manifest>.json
```

Startup fails closed when a legacy, mixed, or interrupted category layout is detected.
   | `--debug` | `False` | Enable debug mode (for development) |

   **Typical Configuration Examples:**

   - **Specify Data Storage Location** (useful for mounted data volumes):
     ```bash
     python app.py --papers-dir /mnt/data/my_papers
     ```

   - **Change Server Port** (if the default port is occupied):
     ```bash
     python app.py --port 8080
     ```

   - **Allow Local Access Only** (for enhanced security):
     ```bash
     python app.py --host 127.0.0.1
     ```
