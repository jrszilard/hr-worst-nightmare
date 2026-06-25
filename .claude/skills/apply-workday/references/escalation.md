# MUST-ESCALATE catalogue

Pause and hand to the user. These are escalated **even when the question is clear**, because the
answer is not a verbatim profile fact, or it is a legal/personal decision. Never guess, never
infer, never auto-tick.

## Unknown-fact questions (no verbatim profile answer)
- **Salary / compensation expectation** — common Workday knockout. Never pick a number.
- **Earliest start date / availability / notice period.**
- **Willingness to relocate.**
- **Years-of-experience-with-<specific tool>** not quantified in the profile.
- **Security clearance** ("do you hold a clearance").
- **Work-authorization nuance beyond the two booleans** — visa type, "are you authorized for
  THIS country/state", "will you EVER need sponsorship" phrased differently than
  `needs_sponsorship`.
- **References** (name/email/phone of third parties) — other people's PII the system doesn't hold.
- **"How did you hear about us"** when required and no truthful option matches.

## Legal attestations (the user must affirm)
- **"Are you over 18 / of legal working age."**
- **Criminal-history / background-check / "have you been convicted."**
- **Acknowledgement / certification / e-signature / typed-name-signature checkboxes**
  ("I certify the above is true", "I consent to the privacy statement").

## Personal-choice demographics (decline-by-default, only with the user's sign-off)
- **Voluntary Disclosures (EEO)** — gender, race/ethnicity, veteran status (incl. protected-veteran
  sub-categories).
- **Self-Identify / CC-305 disability** — propose "I do not wish to answer"; the user decides. On
  CC-305 the Name/Date are factual (real name + today); the disability answer is the user's choice.

## Hard interactive gates (only a human can clear)
- **CAPTCHA** — at BOTH account creation and final submit (the two hotspots). Never solve.
- **Email verification link** AND the **6-digit sign-in code** variant — go to the user's inbox
  (tell them to check spam/promotions).
- **The final Submit click** — the one unrecoverable action; the user always clicks it.

## State/recovery escalations
- **"You have already applied"** hard-block mid-wizard → STOP; reconcile the `applied` flag.
- **Account already exists** on signup → switch to Sign In (don't loop on signup).
- **Session timeout / re-login redirect** mid-flow → re-auth from the vault, resume from the saved
  page (use Save and Continue at each page boundary).
- **Vault save not confirmed** → surface the generated password to the user in chat; never write
  it to disk.
- **Upload unconfirmed** (no filename shown) or **resume parse didn't settle** → escalate; don't
  proceed on a half-rendered page.
- **Page-type Unknown / low confidence** → STOP, ask which page this is.
- **Any field value that can't be verified on re-read** → escalate rather than leave a wrong value.
