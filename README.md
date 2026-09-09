# PaperPilot

<div align="center">

<img src="static/images/paperpilot-github-banner.png" width="100%" />

**A Fully Open-Source, AI-Native Paper Reading & Management Platform**

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Alpha-orange)]()

[English](README.md) | [中文](README_zh.md)

</div>

---

> This project is developed based on the open-source project [Resophy](https://github.com/Mountchicken/Resophy). Special thanks to the original author for their interesting creation.

## 📖 Introduction

<div align="center">
  <iframe src="//player.bilibili.com/player.html?bvid=BV1kGcGzdEYk&page=1&high_quality=1" scrolling="no" border="0" frameborder="no" allowfullscreen="true" width="100%"></iframe>
</div>

**PaperPilot** is a next-generation research assistant designed to streamline your academic workflow. By integrating advanced AI capabilities with a robust document management system, PaperPilot helps you discover, read, understand, and manage research papers more efficiently than ever before.

Whether you are tracking the latest ArXiv preprints or deep-diving into complex PDFs, PaperPilot acts as your intelligent co-pilot.

> **Note**: This project was built using **Trae Coding Agent** via **Vibe Coding**, leveraging two models (**Gemini-3-Pro-Preview** for feature development and **GPT-5.2** for bug fixes and performance optimization). It is truly incredible for someone like me who hasn't written modern Web frontend code 🤯 (the last time I wrote Web code was manually coding HTML and CSS during my undergraduate years).

## ✨ Key Features

### 📚 Smart Paper Management
- **Seamless Upload**: Drag & drop PDF uploads with automatic metadata extraction.
- **Organization**: Custom categories, folders, and full-text search.
- **Zotero Integration**: One-click import from Zotero RDF libraries.
- **Reading Heatmap**: Visualize your reading habits with a GitHub-style contribution graph.

### 🤖 AI-Powered Reading Assistant
- **AI Translation**: Generate pixel-perfect English-to-Chinese (and other languages) translations using **BabelDOC**, preserving original layout and charts.
- **AI Interpretation**: Deep analysis of papers using **MinerU** (PDF-to-Markdown) and LLMs to generate structured summaries (Abstract, Methods, Experiments, Conclusions).
- **Chat with Paper**: Interactive Q&A with your documents to clarify concepts and details.

### 📡 Daily ArXiv Radar
- **Automated Tracking**: Schedule daily fetches from specific ArXiv categories (e.g., `cs.CV`, `cs.AI`).
- **Smart Filtering**: Filter papers by keywords, institution weights, and more.
- **AI Summarization**: Automatically generate concise summaries for new arrivals.
- **Offline Capable**: Works even without LLM connections (skips summary/institution details).

## 📸 Feature Showcase

### 📡 Daily ArXiv Tracking
Automated daily paper fetching with AI summaries to keep you updated.
<div align="center">
  <img src="static/images/snapshots/Daily-arxiv-1.png" width="48%" />
  <img src="static/images/snapshots/Daily-arXiv-2.png" width="48%" />
</div>

### 🤖 AI Interpretation & Chat
Deep full-text analysis and interactive Q&A to bridge language and understanding gaps.
<div align="center">
  <img src="static/images/snapshots/AI-Interpretion.png" width="48%" />
  <img src="static/images/snapshots/AI-Chat.png" width="48%" />
</div>

### 📚 Management & Configuration
Efficient reading list management and flexible system configuration.
<div align="center">
  <img src="static/images/snapshots/Reading-List.png" width="48%" />
  <img src="static/images/snapshots/setting-overview.png" width="48%" />
</div>

### 🔐 Secure Authentication & Access Control
Supports user authentication for secure private access and public network deployment.
<div align="center">
  <img src="static/images/snapshots/login.png" width="48%" />
</div>

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, Flask
- **Frontend**: HTML5, CSS3, Vanilla JS (Responsive)
- **Database**: SQLite (metadata, local accounts, and encrypted settings)
- **AI Core**:
  - [MinerU](https://github.com/opendatalab/MinerU) (High-fidelity PDF parsing)
  - [BabelDOC](https://github.com/funstory-ai/BabelDOC) (Document Translation)
  - OpenAI-compatible LLM Interface

## 🚀 Installation

We recommend using [uv](https://github.com/astral-sh/uv) for fast and reliable dependency management.

### Prerequisites
- Python 3.10 or higher
- `uv` package manager

### Steps

1. **Clone the Repository**
   ```bash
   git clone https://github.com/flyflypeng/PaperPilot
   cd PaperPilot
   ```

2. **Initialize Environment**
   ```bash
   uv venv
   source .venv/bin/activate  # Linux/macOS
   # .venv\Scripts\activate   # Windows
   ```

3. **Install Dependencies**
   
   **Option A: Standard (Client-only)**
   Suitable if you use external APIs for AI tasks.
   ```bash
   uv pip install -e ".[local]"
   ```

   **Option B: Full Server (Local AI)**
   Includes dependencies for local MinerU and VLM inference.
   ```bash
   uv pip install -e ".[server]"
   ```

4. **Local authentication (required in production)**

   PaperPilot uses local usernames and Argon2id password hashes. It does not require an email address or Supabase. Production starts fail-closed in `local` mode and requires at least one active administrator.

   Copy the environment template, initialize the database, and create the first administrator through hidden interactive input:
   ```bash
   cp .env.example .env
   python -m paperpilot.auth_cli --db db/paperpilot.db create-admin --username ifzzh
   ```

   The temporary password is never accepted on the command line or through an environment variable, and the first login must change it. Administrators generate one-use, 24-hour invite codes for ordinary users from **Settings → Administration**. Users, papers, categories, files, settings, chats, tasks, reading data, and encrypted AI credentials are isolated by immutable user UUID.

   Set `PAPERPILOT_COOKIE_SECURE=true` behind HTTPS. For localhost-only development, `development + local + COOKIE_SECURE=false` is supported. Explicit `development + disabled` remains test-only and must never be exposed.


5. **Run the Application**

   For local development only, start the Flask development server:
   ```bash
   python app.py
   ```
   Access the web interface at `http://localhost:7191` (default port).

   **Custom Launch Arguments:**
   `app.py` supports the following command-line arguments for custom configuration:

   | Argument | Default | Description |
   | :--- | :--- | :--- |
   | `--papers-dir` | `./papers` | Path to the papers directory (absolute or relative) |
   | `--host` | `0.0.0.0` | Server listening address |
   | `--port` | `7191` | Server listening port |

   Production containers use one Gunicorn `gthread` worker with eight threads. The maintained Compose file uses the v0.11.0 Web with the compatible v0.10.5 Translation Worker and v0.10.4 Document Worker. Component versions are tracked in `docker/release-components.json`; unchanged services keep their previously verified digest instead of being rebuilt for every PaperPilot release. The Web service binds only `127.0.0.1:7191`; Worker ports `7192` and `7193` are internal only. All three run as non-root users.

   ```bash
   install -d -m 2770 /mnt/raid1/projects/paperpilot/data/staging/translation
   openssl rand -hex 32 > /mnt/raid1/projects/paperpilot/deploy/paperpilot-worker.token
   openssl rand -hex 32 > /mnt/raid1/projects/paperpilot/deploy/paperpilot-document-worker.token
   openssl rand -out /mnt/raid1/projects/paperpilot/deploy/paperpilot-settings.key 32
   chmod 0640 /mnt/raid1/projects/paperpilot/deploy/paperpilot-worker.token
   chmod 0640 /mnt/raid1/projects/paperpilot/deploy/paperpilot-document-worker.token
   chmod 0640 /mnt/raid1/projects/paperpilot/deploy/paperpilot-settings.key
   ```

   The translation Worker receives only `/work/jobs` and its token. The Document Worker receives only a 3 GiB tmpfs mounted at `/work/document-jobs` and its separate token, and has no public network or host port. Neither Worker mounts the paper library, SQLite database, `.env`, settings key, or Docker socket. Successful output is validated and atomically copied into the paper library by the Web service.

   `/healthz` is the container liveness endpoint. `/readyz` additionally checks SQLite and both Workers and may return `503` during a Worker outage without causing a Web restart loop.

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

For an installation already on v0.10.2, stop all services, back up SQLite and the paper directory, then run `python -m paperpilot.migrations.v0103_daily_assets --db /path/to/paperpilot.db --dry-run` followed by `--apply --backup-dir /path/to/backups`, as documented in [the v0.10.4 release notes](docs/releases/v0.10.4.md). The migration adds persistent Daily arXiv asset leases and requeues unfinished candidates without rerunning LLM enrichment or moving PDFs. Deploy all three v0.10.4 image digests together. Rollback restores the migration manifest backup and all three v0.10.2 image digests.

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

## 🧪 Testing

Install the test dependencies:
```bash
uv pip install -e ".[test]"
```

Run the fast unit tests, including mocked arXiv behavior:
```bash
uv run pytest -q -m "not integration"
```

Run only the tests that access the live arXiv API and validate the real response format:
```bash
uv run pytest -q -m integration
```

Run the arXiv-related tests directly:
```bash
uv run pytest -q tests/test_arxiv_api_interactions.py
```

The `integration` tests require network access and depend on arXiv availability. If arXiv is temporarily unavailable or rate-limited, rerun them later.

## ⚙️ Configuration

PaperPilot is designed to be configurable directly from the Web UI.

### arXiv-only proxy
Set `ARXIV_PROXY` when only arXiv metadata/PDF requests should use a proxy:

```bash
ARXIV_PROXY=http://127.0.0.1:7890
```

Scheme-specific overrides are also supported: `ARXIV_HTTP_PROXY` and
`ARXIV_HTTPS_PROXY`. These variables are applied only to `arxiv.org` and
`export.arxiv.org`; DBLP, LLM providers, MinerU, and other backend
requests are not proxied by this setting.

When baking the value into a Docker image:

```bash
docker build --build-arg ARXIV_PROXY=http://host.docker.internal:7890 -t paperpilot .
```

### Agentic Settings
Navigate to the **Settings** tab to configure:
- **LLM Provider**: Set your API Key, approved Base URL, and Model Name (e.g., GPT-4, Qwen, DeepSeek). Saved keys are never displayed again; an empty key keeps the existing value and the separate Clear button removes it.
- **MinerU**: Choose between Local instance or Cloud API.

### Daily ArXiv
Configure your research interests:
- **Categories**: Select ArXiv categories to monitor.
- **Keywords**: Define keywords for filtering and highlighting.
- **Schedule**: Set the automatic fetch interval.
- **Max Papers per Day**: Cap the total number of papers fetched per arXiv date. The recommended default is `50`.
- **Max New Papers per Category per Fetch**: Limit how many new papers each configured category can add in a single sync, so repeated syncs can pick up papers released later in the day.
- **Replacement Candidate Limit**: When a category quota is already full, screen a small number of newer candidates for possible replacement.

The core paper filtering pipeline is:

1. **arXiv category and date filter**: PaperPilot queries each configured category with `cat:<category>`, sorted by newest submissions, and keeps only papers that belong to the target arXiv announcement date. Already downloaded Daily ArXiv papers are skipped.
2. **Keyword hard filter**: If **Keywords** is not empty, a paper must match at least one configured keyword in its title or abstract. Matching is case-insensitive and normalizes punctuation and whitespace.
3. **Quota filter**: The remaining candidates must fit both the daily global budget and the per-category budget. Each sync also respects **Max New Papers per Category per Fetch**.
4. **Institution tier hard filter**: Because arXiv metadata does not provide affiliations, PaperPilot downloads the candidate PDF first, extracts first-page affiliations through the configured LLM, then applies the selected quality strategy as a hard gate:
   - `strict`: keep Tier S/A papers; reject Tier B/C and unknown institutions.
   - `balanced`: keep Tier S/A/B papers and allow unknown institutions; reject Tier C.
   - `discovery`: keep Tier S/A/B/C papers and allow unknown institutions.
   Papers rejected by this gate are not saved, summarized, or shown in Daily ArXiv.
5. **AI enrichment**: Accepted papers get thumbnails, affiliation/country/project-link metadata, and an LLM-generated brief summary and keyword tags when the Daily ArXiv LLM configuration is available.
6. **Replacement screening when full**: When a category is already full, PaperPilot can evaluate a small number of newer candidates against already kept papers and replace a weaker paper only if the LLM judges the candidate clearly better.

Daily ArXiv can split the daily paper budget in two ways:

- **Custom category ratios**: In **arXiv Categories**, set per-category percentages when you want direct control, for example `cs.CV 60%`, `cs.AI 25%`, `cs.LG 15%`. Custom ratios must total exactly `100%`; PaperPilot will warn you if the total is above or below 100%.
- **Automatic weighted split**: If no custom ratios are configured, PaperPilot keeps the existing weighted strategy.

The automatic strategy uses incremental weighted quotas when fetching multiple configured categories:

1. **Weighted reservation**: PaperPilot dynamically recalculates a per-category quota from the current **Categories** list every time settings are saved or fetches run. High-volume AI categories such as `cs.AI`, `cs.CV`, and `cs.LG` receive slightly lower weights, while smaller systems/infrastructure categories such as `cs.DC`, `cs.OS`, `cs.NI`, and `cs.PF` receive higher weights so they are not crowded out.
2. **Incremental intake**: Each sync only admits up to **Max New Papers per Category per Fetch** new papers per category. This avoids filling the whole daily budget during an early sync before arXiv has released papers throughout the day.
3. **LLM replacement screening**: When a category quota is already full, PaperPilot can send newer candidates and the existing papers in that category to the configured LLM. The payload includes paper metadata, abstracts, affiliations, countries, and the current **Institution tiers** configuration. The LLM should replace an existing paper only when the candidate is clearly more valuable; institution tier is used only as one signal when quality and relevance are otherwise comparable.

This keeps niche categories visible, avoids consuming all daily slots too early, and lets later high-value papers replace weaker earlier picks.

## ⚠️ Important Notes

- **Multi-User Support**: v0.9.0 uses local usernames and invitation-only registration. Papers, files, settings, chats, jobs, reading data, and AI credentials are isolated by user UUID; administrators cannot retrieve another user's API keys.
- **BabelDOC Translation**: The English-Chinese parallel translation feature based on BabelDOC has high memory consumption and a long processing time. It is recommended to use this feature primarily for papers that require intensive reading.

## 🗺️ Roadmap

> Contributions are welcome! This roadmap is a living document and will evolve with user needs and available time.

### Near-Term (Next)
- [ ] Reading annotations: highlights, comments, bookmarks, and one-click quote snippets
- [ ] Paper chat improvements: grounded answers with page/paragraph/snippet references
- [ ] Daily ArXiv rules upgrade: keyword combinations, exclusions, regex
- [ ] Deployment & ops: Docker Compose, automated backup/restore, health checks

### Mid-Term (Mid)
- [ ] Semantic search: local embeddings index (optional vector store) with cross-library search
- [ ] Personal knowledge base: turn notes/summaries into a queryable research log (topics/timeline)
- [x] Translation queue & progress center: persistent per-user queue with structured progress, pause, resume and retry

### Long-Term (Future)
- [ ] Multi-tenancy: isolate libraries and settings per user/team
- [ ] Paper recommendations & graph: citation-network and reading-behavior signals
- [ ] Collaborative workspace: shared folders, team annotations, access control
- [ ] Multimodal understanding: structured extraction for figures/equations/tables and searchability
- [ ] Mobile/PWA: offline reading and cross-device sync

### Performance & UX (Ongoing)
- [ ] Faster PDF rendering, page cache, and on-demand loading for long documents
- [ ] Incremental indexing for global search (avoid full rescans)
- [ ] Configuration validation and one-click diagnostics (LLM/MinerU/BabelDOC)
- [ ] Observability: job timings, failure reasons, and basic metrics


## 📄 License

This project is licensed under the **CC BY-NC 4.0** License. See the [LICENSE](LICENSE) file for details.

---
<div align="center">
Made with ❤️ by the PaperPilot Team
</div>
