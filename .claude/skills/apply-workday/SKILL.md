---
name: apply-workday
description: Use to drive a Workday (myWorkdayJobs) job application in the user's real Chrome via the Chrome MCP — per-employer account creation captured by the browser password vault, per-page human review, never auto-submit. Triggers on "apply to <job> on Workday", "do this Workday application", external/Workday apply.
---

# Workday Assisted Apply (in-session, Chrome MCP)

> This runbook is the agent-driven implementation of the Track B `BrowserEngine` vocabulary
> (see `docs/superpowers/specs/2026-06-12-track-b-browser-engine-design.md`). It is the same
> `snapshot → fill/select/upload → await_human` shape as the Python deterministic driver in
> `backend/platforms/browser/apply_driver.py` — one vocabulary, two interpreters.

You drive the user's **real Chrome** via `mcp__claude-in-chrome__*` to fill a Workday
application while the user watches and approves each page. You fill; **the user clicks the
final Submit.** Read `references/escalation.md` and `references/workday-mechanics.md` before
driving. This runs entirely in a Claude Code session — the FastAPI backend cannot drive the
Chrome MCP.

## Hard rules (never violate)
- **Never auto-submit.** `await_human` is the terminal step of every page — the final Submit
  click is always handed to the user via `await_human("Review page — you click Submit")`. Before
  EVERY advance click, read the button's accessible label; if it matches `/submit|apply now/i`,
  STOP and call `await_human`. On the Review page, never click any primary button.
- **Never fabricate.** `fill` and `select` only values present verbatim in the apply package /
  profile. Anything missing → escalate (see `references/escalation.md`). Never invent a name,
  title, employer, date, degree, salary, or metric.
- **Never solve/bypass CAPTCHA; never spoof behaviour.** Call `await_human("CAPTCHA")`.
- **No credentials in files.** Passwords live only in the browser vault. If the vault save can't
  be confirmed, surface the generated password to the user in chat so they save it manually —
  never write it to disk.

## Step 0 — Prepare the package (no browser)
Run: `python scripts/prepare_apply.py <job_id>` and read the JSON. It gives `resolved_url`,
`cover_letter`, `cover_letter_pdf_path`, `resume_path` (already in a session-shared dir),
`applicant{}` (canonical identity), `work_history[]`, `education[]`, `skills[]`. If
`work_history` is empty, you will escalate the My-Experience employment section (Step 5). If
`resolved_url` is null, resolve in-session (Step 1).

## Step 1 — Open / resolve the URL
`goto(resolved_url)` if set. Else open the stored aggregator URL, click "Apply on company
website", follow the redirect, read `window.location`, and assert the host is a Workday host
(see mechanics ref). If it stays on the aggregator domain, STOP — not a Workday apply.

## Step 2 — Account-wall handshake (browser vault)
- Call `snapshot()` to read the login/signup fields.
- If a Sign In autofills from the vault → `fill` the credential fields and sign in. If
  "account already exists" on signup → switch to Sign In. Else Create Account: `fill` the
  canonical email, generate a 16+ char strong password (upper/lower/digit/special), `fill`
  BOTH "New Password" and "Verify New Password", `select`/tick the terms checkbox. Read the
  on-page password rule via `snapshot()`; regenerate and `fill` again if rejected.
- After submit, confirm the success / "verify your email" state.
- VAULT CHECKPOINT → `await_human("Vault checkpoint — confirm Chrome saved the password")`:
  confirm Chrome offered "Save password?" and the user accepted. If no prompt appeared, paste
  the generated password in chat so they save it manually.
- EMAIL-VERIFY GATE → `await_human("Email verification — click the link in your inbox (check
  spam/promotions); some tenants use a 6-digit sign-in code")`. Wait, then confirm a signed-in
  Candidate Home.

## Step 3 — Per-page loop (every wizard page)
1. **SETTLE:** after `goto`/Next/upload, call `snapshot()` repeatedly until the page anchor
   label is present, no spinner remains, and two successive snapshots are stable. Never act on
   the first snapshot; never use fixed sleeps. For heavy pages use scoped reads
   (`filter='interactive'` / per-section) — a full `snapshot()` can overflow the ~50k cap.
2. **CLASSIFY** by content signature into {MyInformation, MyExperience, ApplicationQuestions,
   VoluntaryDisclosures, SelfIdentify, Review, Unknown}. On Unknown → `await_human("Unknown
   page type — please tell me what this page is")`.
3. **FILL:** from the `snapshot()` field list, build values (identity/screening/EEO mapping
   from the package), then for each field: resolve a FRESH ref (carry `data-automation-id` —
   never cache refs across a re-render), call `fill(field, value)` for text inputs,
   `select(field, option)` for dropdowns. Re-call `snapshot()` to verify the value landed;
   escalate on mismatch.
4. **HANDOFF:** show the user the filled state and call
   `await_human("Review filled page — OK to advance?")`. Advance only after confirmation
   (obeying the never-submit rule).

## Steps 4–9 — Page specifics
- **My Information:** `snapshot()` then `fill`/`select` identity from the canonical
  `applicant{}` (always overwrite Workday's prefill); `select` work-auth/sponsorship from the
  two booleans. "How did you hear about us" with no truthful option → escalate.
- **My Experience:** `upload(resume_field, resume_path)` to the HIDDEN file input by ref
  (never click the visible dropzone). The Chrome MCP `file_upload` tool rejects host filesystem
  paths — call `await_human("Upload resume — use the native file picker at: <staged_path>")` so
  the user uploads via the OS native picker. Wait for the async parse to settle (poll
  `snapshot()` until parse fields stabilize). Then OVERWRITE the parse with
  `work_history[]`/`education[]` as ground truth, entry-by-entry by index (`fill`/`select` each
  field after clicking Add; re-call `snapshot()` between entries). Dates: `select` month+year
  sub-controls, verify. Skills: type-ahead → `fill` the prompt and `select` the option chip →
  escalate if no match. **If `work_history` is empty → escalate the whole employment section.**
  Any field backed by neither package nor profile → escalate.
- **Application Questions:** `snapshot()` live. `fill` only open-ended role questions, grounded
  strictly in the profile/cover letter. Everything on the MUST-ESCALATE list →
  `await_human("Application Questions — salary, start date, relocation, location prefs, opinion
  surveys, 'relatives at company', 'applied to sister company' etc. are yours to fill")`. Only
  the two work-auth questions are auto-fillable from the booleans (legally-entitled = Yes for a
  citizen; sponsorship = No).
- **Voluntary Disclosures / Self-Identify (CC-305):** ALWAYS a human-decision checkpoint. Call
  `await_human("Voluntary disclosures — your choice; 'I do not wish to answer' is suggested for
  all fields")`. Never `select` a real demographic value. On CC-305, `fill` name/date (factual);
  the disability answer is the user's choice via `await_human`.
- **Review:** `snapshot()` to verify all sections; summarise for the user. Call
  `await_human("Review page — you click Submit")`. Never click any primary button here.

## Step 10 — Record the result
After the user confirms they submitted (on-screen confirmation or Candidate Home →
My Applications; a missing confirmation email is NOT failure), run:

```bash
curl -s -X POST http://localhost:8000/api/jobs/<job_id>/applied \
  -H 'Content-Type: application/json' -d '{"applied": true}'
```

"Apply is not complete until `applied=true` is recorded."

## Recovery
- **Session timeout:** `snapshot()` will start returning stale/error states (probe the package
  endpoint — a 401 confirms a dead session). Call `await_human("Session timed out — re-auth
  needed")`, re-auth from the vault, then resume. Use Save and Continue at each page boundary
  before pausing — a saved page survives a timeout; an unsaved one is lost.
- **Re-auth reality:** after re-login, a fresh application instance does NOT re-populate My
  Experience from the prior draft, and re-clicking "Autofill with Resume" does NOT re-parse →
  expect full manual re-entry. Keep a complete documented record of every field (from prior
  `snapshot()` calls) so re-entry is mechanical; add entries chronologically (newest first). My
  Information persists to the candidate profile; a previously-uploaded resume persists too.
- **Already-applied hard block:** STOP, reconcile applied flag.
- **Upload unconfirmed / parse not settled / ref mismatch:** escalate that field.

## Lessons from the first live run (PHLY/Tokio Marine, 2026-06-09 — submitted)
- **RACE THE SESSION TIMEOUT — this is the #1 risk.** A long, chatty editing session timed out:
  every save started returning 400 (probe the package endpoint → 401 confirms a dead session),
  the My Experience edits had never persisted, and re-auth wiped the page. Work in tight
  `browser_batch` calls, minimize idle Q&A on a page, and get each page to a **successful** Save
  and Continue before pausing. A saved page survives a timeout; an unsaved one is lost. Invoke
  `await_human` for page review only — do not pause mid-page.
- **Recovery reality:** after re-login, a fresh application instance does NOT re-populate My
  Experience from the prior draft, and re-clicking "Autofill with Resume" did NOT re-parse →
  expect **full manual re-entry**. Keep a complete documented record of every field (from your
  `snapshot()` calls) so re-entry is mechanical; add entries chronologically (newest first). My
  Information persisted to the candidate profile; the previously-uploaded resume persisted too.
- **`upload` / native picker constraint:** `file_upload` (Chrome MCP) rejects host filesystem
  paths ("no longer accepts host paths"). Use `await_human("Upload resume — native file picker,
  path: <staged_path>")` so the HUMAN picks the file. This also means the resume must be correct
  BEFORE upload (regenerate + call `await_human` to re-upload on any change).
- **The resume parse is excellent** when given a complete, accurate PDF: it fills
  title/company/dates/description/GPA. `snapshot()` → overwrite-with-ground-truth beats manual
  entry — but verify every `snapshot()` field (year-only resume dates default to January; confirm
  real months with the user via `await_human`).
- **Application Questions is a heavy-escalation page** (salary = required knockout, start date,
  relocation, location prefs, opinion surveys, "relatives at company", "applied to a sister
  company"). The USER fills it via `await_human`. Only the two work-auth questions are
  auto-fillable via `fill` from the booleans (legally-entitled = Yes for a citizen; sponsorship
  = No).
- **Skills / Field-of-Study prompts** may not contain the user's real terms (this tenant lacked
  "Power BI"/"Tableau"). Both are optional — don't rabbit-hole; skip and move on.
