# Contract Finder & Applyer

AI-powered contract discovery and proposal generation for freelancers. Scans Upwork listings via browser automation, matches them against your skill profile, scores ROI, and generates tailored proposals using Claude AI.

## How It Works

```
Job Boards  ──►  Scanner  ──►  Skill Matching  ──►  ROI Scoring  ──►  Application Generation
(Upwork +         (Chrome MCP       (fuzzy + aliases)    (win probability)   (writing pipeline
 full-time jobs)   / direct fill)                                              + Claude AI)
```

The pipeline handles **both freelance contracts and full-time jobs**, not just Upwork:

1. **Scan** — A Chrome MCP-based agent navigates job boards (Upwork and others), extracts listings, and persists them to SQLite. Each opportunity carries a `kind` (contract or job) and a `submission_channel` that determines how it is submitted.
2. **Match** — Each listing's required skills are matched against your profile using alias resolution and substring matching (core skills weighted 1.0, adjacent 0.6)
3. **Score** — Opportunities are ranked by ROI: `(match_score * contract_value * win_probability) / (connects_cost + time_cost)`
4. **Analyze** — Claude extracts the client's real problem and implicit needs from the listing
5. **Apply** — Claude generates a tailored application (proposal or cover letter) through a multi-stage writing pipeline, then runs an **assisted browser fill** on the hosted form (Greenhouse/Lever/Ashby). It stages your résumé + cover-letter PDF, fills only what it can ground from your profile, and **never clicks final submit** — the pre-filled form is left open for your review, captcha, and submit.

## Architecture

```
backend/
  main.py              FastAPI app (lifespan, CORS, router registration)
  config.py            Pydantic settings from .env
  api/                 REST routers — contracts, scanner, proposals, availability, history
  core/                Business logic — matching, scoring, availability, models, enums
  ai/                  Claude integration — contract analyzer, proposal generator, prompt templates
  db/                  SQLAlchemy async models + database setup
  platforms/upwork/    Chrome MCP scanner, adapter, submission, MCP utilities
  portfolio/           Case study loader (markdown), profile loader

frontend/
  src/pages/           ContractFeed, ProposalReview, Settings, History
  src/components/      ContractCard, FilterBar, ProposalEditor, ROIBadge, ScanButton, etc.
  src/lib/             API client and utilities

profile/                 Your profile bundle (copy from profile.example/)
  profile.yaml         Your freelancer profile (skills, positioning, rates)
  searches.yaml        Search query definitions (categories, filters, budget floors)
  case-studies/        Markdown case study files for proposal generation
  contracts.db         SQLite database (auto-created on first run)
```

## Get started (self-host)

1. `git clone <repo> && cd contract-finder-and-applyer`
2. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. `cp -r profile.example profile` and `cp .env.example .env`
4. Set `ANTHROPIC_API_KEY` in `.env` (keep `PROFILE_DIR=profile`).
5. Drop your résumé + `links.txt` + work samples into `profile/inputs/` (see its README).
6. `./onboard.sh` — generates `profile/profile.yaml` + `profile/case-studies/`. Review them.
7. `./run.sh` — starts the API + UI.

`./run.sh` starts the FastAPI backend at `http://localhost:8000` and the Vite UI at
`http://localhost:5173`, then stops both when you press `Ctrl+C`. Logs are written to
`.backend.log` and `.frontend.log`.

### Seed Test Data (optional)

```bash
python scripts/seed_test_data.py
```

## Configuration

### Profile (`profile/profile.yaml`)

Define your skills, positioning, hourly rate range, selling points, and key differentiators. The matching engine uses this to score contracts against your expertise.

### Searches (`profile/searches.yaml`)

Configure Upwork search queries by category (reporting, data, AI) with filters for experience level, minimum budget, and job type.

### Job boards (`profile/job_boards.yaml`)

Configure full-time/staff-style job discovery. Greenhouse/Lever/Ashby public APIs are company-board APIs, so the file contains a watched-company list plus criteria filters (`title_include_any`, `text_include_any`, `skills_include_any`, `exclude_title_any`) to keep US-based data/AI/analytics roles and avoid obvious non-fits. Run `PYTHONPATH=. python scripts/scan_job_boards.py` to scan the configured watchlist.

### Case Studies (`profile/case-studies/`)

Add markdown case studies that the proposal generator references. Each file includes client name, category, challenge, solution, tools used, and key metrics. The AI uses these to write authentic, evidence-backed proposals.

## Key Features

- **Fuzzy skill matching** — 50+ skill aliases map job board tags to your profile (e.g., "Microsoft Power BI" matches "Power BI")
- **ROI scoring** — Factors in match quality, contract value, client hire rate, competition level, connects cost, and your time value
- **Percentile indicators** — Green/yellow/red ranking relative to other scanned opportunities
- **AI contract analysis** — Extracts skills, identifies the real client problem, and surfaces implicit needs
- **Structured proposals** — 5-section format (hook, experience, approach, differentiator, CTA) with annotations explaining each choice
- **Case study grounding** — Proposals reference your actual project history, with hallucination guards that validate case study IDs
- **Side-by-side editor** — Review and edit proposals before submitting, with annotation markers
- **Availability filtering** — Auto-filters opportunities below your rate floor or outside preferred contract type
- **Human-sounding output** — every generated application passes through a writing
  pipeline: a deterministic sanitizer (removes em-dashes, arrows, `+`-as-and, smart
  quotes), an LLM critic rewrite, and a prompt-injection / "are you an AI" trap scanner
  that flags embedded traps for human review instead of obeying them.
- **Board-agnostic model** — opportunities carry a `kind` (contract or job), a
  `submission_channel` (direct fill or Claude-in-Chrome), and board-specific data in a
  `platform_meta` JSON field.
- **Assisted apply, human-in-the-loop** — for hosted ATS forms the engine fills the
  fields it can, stages your résumé + cover-letter PDF into a predictable folder, and hands
  off to you for the steps a browser extension can't or shouldn't do (file upload, captcha,
  final submit). It never auto-submits.
- **Anti-confabulation grounding at fill time** — demographic/EEO, work-authorization,
  salary, consent, and "how did you hear about us" referral-source fields are never
  auto-answered; they escalate to you. Only questions that can be grounded in your real
  profile and case studies get a generated answer, so the form never invents a fact.
- **Identity & hosted-form handling** — name, email, phone, LinkedIn, GitHub, and website
  are filled from structured profile data (never written as prose); Greenhouse listing URLs
  that gate the form behind an "Apply" click are rewritten to the canonical `/embed/job_app`
  form so the fields are present when the engine reads the page.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, FastAPI, SQLAlchemy, aiosqlite |
| AI | Anthropic Claude API (Sonnet) |
| Frontend | React 19, React Router 7, Tailwind CSS 4, Vite |
| Browser Automation | Chrome MCP (Model Context Protocol) |
| Database | SQLite (async) |
| Portfolio | Local markdown case studies |
| Config | Pydantic Settings, YAML |
| Testing | pytest, pytest-asyncio, respx |

## Testing

```bash
# Run all tests
pytest

# Run a specific test module
pytest tests/test_scoring.py -v
```

The test suite covers: scoring, matching, API endpoints, platform adapters, proposal generation, profile loading, database operations, CMS client, contract analysis, and Chrome scanner.

## License

MIT
