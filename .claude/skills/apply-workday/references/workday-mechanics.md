# Workday mechanics (from research; validate live on the first real tenant)

## URL families (both live)
- `<tenant>.wd<N>.myworkdayjobs.com/<locale?>/<site>/job/<slug>_<reqId>` — tenant in the
  **subdomain**. Examples: `wgu.wd5.myworkdayjobs.com/en-US/External/job/...JR-025267`,
  `accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers/job/...AIOC-S01625580-1`.
- `wd<N>.myworkdaysite.com/<locale?>/recruiting/<tenant>/<site>/...` — tenant in the **path**.
  Examples: `wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs` (Wells Fargo),
  `wd5.myworkdaysite.com/recruiting/uw/UWHires` (UW).
- **Never hardcode the data-center cell** (`wd1/wd3/wd5/wd103/wd105` all real). Keep the req
  `-1/-2` version suffix — it is part of the path; stripping it 404s.
- `locale` (`en-US`) is sometimes present, sometimes absent — treat as optional.

## Apply route
- The description page renders an "Apply" button; the apply flow is a deep-linkable SPA route:
  `<descriptionUrl>/apply/autofillWithResume` (resume-parse) or `/apply/applyManually` (no prefill).
- The apply route gates on **Sign In / Create Account** first. **No guest apply** on Workday.

## Aggregator → employer resolution
- JSearch `apply_options[]` often lists LinkedIn/Indeed/ZipRecruiter + the employer's own entry.
  Prefer the entry whose **host** is a Workday host; **ignore the `is_direct` flag** (unreliable).
- If only a LinkedIn/Indeed/ZipRecruiter URL exists: navigate it, click "Apply on company
  website", follow the redirect, read `window.location`, assert the host is Workday. If it stays
  on the aggregator domain, it is NOT a Workday apply — stop.

## Accounts & auth
- Accounts are **per-tenant** (per employer subdomain). Credentials never transfer; every new
  employer = a new signup + email verification.
- Create Account form: **email + New Password + Verify New Password (two fields) + terms checkbox**.
  Default password policy is 8-char/upper/lower/special but is **tenant-configurable** (some need
  12–14+) — generate **16+** chars to clear the strictest, and read the on-page rule hint to
  regenerate on rejection.
- Email verification is an **activation link** that generally gates account activation **before**
  the wizard; some tenants instead/also use a **6-digit sign-in code**. Both go to the user's
  inbox — escalate and wait.
- Some 2025R2 tenants offer **Sign in with Google/Apple** (not LinkedIn/Microsoft for candidates).
  If present and the user prefers it, it can replace email+password. Email+password is the default.
- The password-manager "Save password?" bubble is **browser-chrome UI** the MCP can't see or
  trigger — confirm with the user that it appeared and was accepted.

## The wizard (standard order; pages can be absent/merged/reordered per tenant)
My Information → My Experience → Application Questions → Voluntary Disclosures →
Self-Identify (CC-305) → Review → Submit. Classify each page by content signature, not a counter.
- **My Information:** legal name, address (country drives the field set), phone, email, "How did
  you hear about us", often work-auth/sponsorship/"previously employed here".
- **My Experience:** the heaviest page and the **only** place to upload documents (≤5 files,
  ≤~5 MB, PDF/DOC/DOCX). Repeatable **Work Experience** (title, company, location, "I currently
  work here", From/To month+year, description) and **Education** (school, degree, field, years).
  **Skills** is a controlled **type-ahead** — free text is rejected; type partial, pick the option
  chip. Optional websites/LinkedIn.
- **Application Questions:** highest-variance, tenant-specific, may contain knockout questions —
  read live.
- **Voluntary Disclosures / Self-Identify:** voluntary; each has "I do not wish to answer".

## Async / DOM gotchas
- Workday is a heavy React SPA; "Next" swaps content client-side (no full reload). Fields and
  inline validation render **late**; a read fired before the spinner clears yields stale/empty
  fields. Re-read until stable before filling or judging required-but-missing.
- Resume **auto-parse is ~34% wrong** (mis-mapped dates/company names) — verify/correct every
  field; never trust it. The package's `work_history[]`/`education[]` is the ground truth.
- The real `<input type=file>` is often **hidden** (`offsetParent===null`). Locate it by ref and
  `file_upload` to it directly — do NOT click the visible "Select Files"/dropzone (opens a native
  picker the MCP can't drive).
- Match fields on stable attributes (`data-automation-id`, `name`, `aria-label`), not volatile
  generated IDs.
- **Identity consistency:** reuse byte-identical name/email/phone across every employer; Workday
  silently **forks a duplicate candidate profile** on any mismatch (plus-addressing, phone format,
  nicknames). Always overwrite Workday's prefilled identity with the canonical `applicant{}`.

## Widget recipes
- **Date pickers:** set the month and year sub-controls individually by ref; verify the displayed
  value.
- **Skills / type-ahead combobox:** clear → type partial → read the dropdown options → click the
  matching option ref → verify it became a chip → escalate if no option matches.
- **Checkbox:** `form_input` boolean by ref.
- **Clear-before-correct:** remove an auto-parsed value before typing the correct one.
