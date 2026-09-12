# PaperPilot → iPaper

The 1.1.4 migration changes branding and runtime identifiers, not application features or licensing. / 本次仅改名和基础设施同步，不增加功能或改变许可。

- Repository: [ifzzh/iPaper](https://github.com/ifzzh/iPaper).
- Images: `ifzzh520/ipaper`, `ifzzh520/ipaper-translation-worker`, `ifzzh520/ipaper-document-worker`.
- Python package: `ipaper`; administrator CLI: `ipaper-auth` or `python -m ipaper.auth_cli`.
- Configuration: `IPAPER_`; legacy `PAPERPILOT_` reads remain supported. Explicit new values take precedence, including empty values. Conflict logs contain names only.

Historical images are copied with their original manifest digests and platform lists, without rebuilding. Old repositories and releases remain historical compatibility sources. Do not overwrite a different existing target tag or create Worker latest tags. The new release rebuilds all three components because package imports and executable entry points changed.

## Existing storage

Stop all writers after tasks become idle. Back up SQLite consistently and preserve configuration, permissions and keys. Rename directories on their current filesystem; do not duplicate a live database or start old and new applications concurrently. Use explicit version@digest image references and existing volume identities.

The maintainer deployment changes `/srv/ifserver-fast/paperpilot` to `/srv/ifserver-fast/ipaper`, `/mnt/raid1/projects/paperpilot` to `/mnt/raid1/projects/ipaper`, and `/mnt/raid1/backups/paperpilot` to `/mnt/raid1/backups/ipaper`. The checkout alias becomes `/home/ifzzh/Project/iPaper`. Old paths remain temporary compatibility symlinks. SQLite becomes `ipaper.db` after writers stop and WAL is checkpointed. Container asset paths, user UUIDs and file contents remain unchanged.

The existing document staging volume is `deploy_document_jobs`: production explicitly declares this external volume. Do not let the new Compose project create an empty replacement. New installations may use the repository Compose's managed volume; existing installations must supply their real volume binding.

## Deliberate old-name compatibility

- Category directory UUID namespace contains the historical repository URL; changing it would change existing physical directories.
- Encrypted settings AAD retains `paperpilot:agentic-secret:…`; changing it would invalidate existing ciphertext.
- `.paperpilot-migrations` retains existing offline migration markers.
- `paperpilot_session` and `paperpilot_csrf` cookies retain session compatibility; logout and CSRF validation are unchanged.
- Old environment variables, historical releases, upstream names, copyright and license statements are not blind-replaced.

## Rollback

Use the restricted backup's migration-specific rollback script, not an earlier release's hardcoded deployment helper. Stop the new services, reverse directory/database filename changes, restore prior Compose/configuration and previous component digests, then verify the existing database and real PDFs. Keep the current database contents; do not overwrite new user writes with a pre-upgrade backup. Restore the new Web latest channel to the copied prior stable digest if necessary. Never remove volumes as part of rollback.

Actual component digests, completed checks and any exceptions are published with the release; private production evidence and backup paths remain in the maintainer migration record.

## Historical artifacts retained

The dated synthetic PDF fixtures and XSS payloads preserve their original content and hashes. Requirements export comments record the original package provenance. Two unused legacy SVG logos remain compatibility assets referenced only by retired templates; the unified routed application uses iPaper branding. They do not provide a second product interface. Active project configuration uses the new checkout path; an already-open Codex window may retain the old project label until it reloads, while the compatibility symlink remains valid.
