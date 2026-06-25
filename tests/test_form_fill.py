from backend.core.models import ApplicantInfo
from backend.platforms.form_fill import (
    FormField, FillAbort, FillPlan, build_fill_plan, extract_screening_questions,
    plan_fill, _identity_value, _build_document_filename,
)


def test_build_document_filename_company_then_position_then_doctype():
    # Staged files must lead with the company so they group together in the growing
    # apply_artifacts folder, while staying descriptive to the hiring manager:
    # FirstLast_<company>_<position>_<DocType>.pdf
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-0100")
    artifact = {"job_title": "Data Analyst III", "company": "renttherunway"}
    assert (_build_document_filename(applicant, artifact, "Resume")
            == "Pat_Sample_renttherunway_Data_Analyst_III_Resume.pdf")
    assert (_build_document_filename(applicant, artifact, "CoverLetter")
            == "Pat_Sample_renttherunway_Data_Analyst_III_CoverLetter.pdf")


def test_sex_and_age_demographic_questions_are_eeo():
    # _EEO_RE had `gender` but not `sex`/`age`, so "best describes your sex" and "age range"
    # leaked to the generator (it declined gracefully, but EEO must be hard-blocked, not
    # left to the model's judgment). Same vocab-gap class as the LGBTQIA fix.
    for q in ["Which of the following best describes your sex?", "Please select your age range."]:
        assert extract_screening_questions([FormField(label=q, kind="textarea")]) == []

APPLICANT = ApplicantInfo(first_name="Pat", last_name="Sample",
                          email="j@example.com", phone="555-1212",
                          resume_path="data/resume.pdf")
ARTIFACT = {
    "cover_letter": "Hello, I'm a strong fit.",
    "screening_answers": [
        {"question": "Why do you want to work here?", "answer": "Mission alignment."},
    ],
}


def test_maps_identity_resume_and_cover(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    fields = [
        FormField(label="First Name", required=True),
        FormField(label="Last Name", required=True),
        FormField(label="Email", required=True),
        FormField(label="Phone", required=False),
        FormField(label="Resume/CV", required=True, kind="file"),
        FormField(label="Cover Letter", required=False, kind="textarea"),
    ]
    plan = build_fill_plan(fields, ARTIFACT, applicant)
    assert isinstance(plan, FillPlan)
    assert plan.values["First Name"] == "Pat"
    assert plan.values["Email"] == "j@example.com"
    assert plan.values["Cover Letter"].startswith("Hello")
    assert "Pat_Sample_Resume" in plan.files["Resume/CV"]
    assert plan.files["Resume/CV"].endswith(".pdf")


def test_build_fill_plan_prefers_staged_resume_and_cover_paths():
    # When the assisted-apply endpoint has already staged the résumé + cover-letter PDF into the
    # shared apply_artifacts dir, plan_fill must use those exact paths for the file fields, so the
    # engine's upload escalation names the staged file the human will find — not a generic résumé
    # copied to a random temp dir.
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample", email="j@example.com",
                              phone="555-1212", resume_path="data/resume.pdf")
    artifact = {**ARTIFACT,
                "resume_path": "/artifacts/Pat_Resume_Data_Analyst_III_rtr.pdf",
                "cover_letter_pdf_path": "/artifacts/Pat_CoverLetter_Data_Analyst_III_rtr.pdf"}
    fields = [
        FormField(label="Resume/CV", required=True, kind="file"),
        FormField(label="Cover Letter", required=True, kind="file"),
    ]
    plan = build_fill_plan(fields, artifact, applicant)
    assert plan.files["Resume/CV"] == "/artifacts/Pat_Resume_Data_Analyst_III_rtr.pdf"
    assert plan.files["Cover Letter"] == "/artifacts/Pat_CoverLetter_Data_Analyst_III_rtr.pdf"


def test_matches_custom_question_to_screening_answer(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    fields = [
        FormField(label="Resume", required=True, kind="file"),
        FormField(label="Why do you want to work here?", required=True, kind="textarea"),
    ]
    plan = build_fill_plan(fields, ARTIFACT, applicant)
    assert isinstance(plan, FillPlan)
    assert plan.values["Why do you want to work here?"] == "Mission alignment."


def test_aborts_on_unmapped_required_field(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    fields = [
        FormField(label="Resume", required=True, kind="file"),
        FormField(label="What is your salary expectation?", required=True, kind="text"),
    ]
    result = build_fill_plan(fields, ARTIFACT, applicant)
    assert isinstance(result, FillAbort)
    assert "salary expectation" in result.reason.lower()


def test_aborts_when_resume_required_but_missing_path():
    applicant = ApplicantInfo(first_name="J", last_name="S", email="e", resume_path="")
    fields = [FormField(label="Resume", required=True, kind="file")]
    result = build_fill_plan(fields, ARTIFACT, applicant)
    assert isinstance(result, FillAbort)
    assert "resume" in result.reason.lower()


def test_optional_unmapped_field_is_skipped_not_aborted(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    fields = [
        FormField(label="Resume", required=True, kind="file"),
        FormField(label="LinkedIn URL", required=False, kind="text"),
    ]
    plan = build_fill_plan(fields, ARTIFACT, applicant)
    assert isinstance(plan, FillPlan)
    assert "LinkedIn URL" not in plan.values


def test_keys_by_id_selector_when_present():
    fields = [FormField(label="First Name*", required=True, id="first_name")]
    plan = build_fill_plan(fields, ARTIFACT, APPLICANT)
    assert isinstance(plan, FillPlan)
    assert plan.values["#first_name"] == "Pat"


def test_file_disambiguation_resume_vs_cover_letter(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    # Both file inputs share the generic Greenhouse "Attach" label; id disambiguates.
    fields = [
        FormField(label="Attach", required=True, kind="file", id="resume"),
        FormField(label="Attach", required=False, kind="file", id="cover_letter"),
    ]
    plan, unfilled = plan_fill(fields, ARTIFACT, applicant)
    assert "Pat_Sample_Resume" in plan.files["#resume"]
    assert plan.files["#resume"].endswith(".pdf")
    assert "#cover_letter" in plan.files        # cover letter file now generated as PDF
    assert plan.files["#cover_letter"].endswith(".pdf")
    assert unfilled == []


def test_plan_fill_reports_unfillable_required_widget():
    # A required custom dropdown surfaces as an unlabeled, id-less control.
    fields = [
        FormField(label="First Name*", required=True, id="first_name"),
        FormField(label="", required=True, kind="text"),  # React-Select combobox
    ]
    plan, unfilled = plan_fill(fields, ARTIFACT, APPLICANT)
    assert plan.values["#first_name"] == "Pat"
    assert len(unfilled) == 1 and unfilled[0].label == ""


def test_combobox_matches_screening_answer_to_option(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 dummy")
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="j@example.com", phone="555-1212",
                              resume_path=str(resume))
    artifact = {"screening_answers": [
        {"question": "Are you authorized to work in the US?", "answer": "Yes"},
    ]}
    fields = [
        FormField(label="Resume", required=True, kind="file"),
        FormField(label="Are you authorized to work in the US?", required=True,
                  kind="combobox", options=["Yes", "No"]),
    ]
    plan = build_fill_plan(fields, artifact, applicant)
    assert isinstance(plan, FillPlan)
    assert plan.selects["Are you authorized to work in the US?"] == "Yes"
    assert plan.values == {}


def test_combobox_substring_match():
    artifact = {"screening_answers": [
        {"question": "Work location preference", "answer": "remote"},
    ]}
    fields = [FormField(label="Work location preference", required=True,
                        kind="combobox", options=["Fully Remote", "Hybrid", "On-site"])]
    plan = plan_fill(fields, artifact, APPLICANT)[0]
    assert plan.selects["Work location preference"] == "Fully Remote"


def test_combobox_no_match_escalates():
    artifact = {"screening_answers": []}
    fields = [FormField(label="Preferred start date bucket", required=True,
                        kind="combobox", options=["Immediately", "1 month", "3 months"])]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert plan.selects == {}
    assert [f.label for f in unfilled] == ["Preferred start date bucket"]


def test_combobox_extracts_leading_yes_no_from_explanation():
    # Answers like "No prior experience" or "Yes, I have 5 years..." should still
    # map to the Yes/No option by extracting the leading word.
    artifact = {"screening_answers": [
        {"question": "Do you have prior experience?", "answer": "No prior experience"},
    ]}
    fields = [FormField(label="Do you have prior experience?", required=True,
                        kind="combobox", options=["No", "Yes"])]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert plan.selects == {"Do you have prior experience?": "No"}
    assert unfilled == []


def test_eeo_combobox_auto_declines():
    fields = [
        FormField(label="Gender", required=True, kind="combobox",
                  options=["Male", "Female", "Decline To Self Identify"]),
        FormField(label="Veteran Status", required=True, kind="combobox",
                  options=["I am a veteran", "I am not a veteran", "I don't wish to answer"]),
    ]
    plan = build_fill_plan(fields, {"screening_answers": []}, APPLICANT)
    assert isinstance(plan, FillPlan)
    assert plan.selects["Gender"] == "Decline To Self Identify"
    assert plan.selects["Veteran Status"] == "I don't wish to answer"


def test_eeo_combobox_without_decline_option_escalates():
    fields = [FormField(label="Race / Ethnicity", required=True, kind="combobox",
                        options=["White", "Asian", "Hispanic or Latino"])]
    plan, unfilled = plan_fill(fields, {"screening_answers": []}, APPLICANT)
    assert plan.selects == {}
    assert [f.label for f in unfilled] == ["Race / Ethnicity"]


def test_non_eeo_label_containing_eeo_substring_is_not_auto_declined():
    # "embrace" contains "race"; "veteran" boundary — must NOT trigger EEO auto-decline
    artifact = {"screening_answers": [
        {"question": "How do you embrace remote work?", "answer": "remote"},
    ]}
    fields = [FormField(label="How do you embrace remote work?", required=True,
                        kind="combobox", options=["Fully Remote", "Hybrid", "On-site"])]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert plan.selects["How do you embrace remote work?"] == "Fully Remote"
    assert unfilled == []


def test_eeo_decline_matches_unicode_apostrophe():
    fields = [FormField(label="Gender", required=True, kind="combobox",
                        options=["Male", "Female", "I don’t wish to answer"])]
    plan = build_fill_plan(fields, {"screening_answers": []}, APPLICANT)
    assert isinstance(plan, FillPlan)
    assert plan.selects["Gender"] == "I don’t wish to answer"


def test_screening_answer_short_label_does_not_match_long_question():
    artifact = {"screening_answers": [
        {"question": "Will you require visa sponsorship to work in the country you applied in?", "answer": "No"},
    ]}
    fields = [FormField(label="Country", required=True, kind="combobox",
                        options=["United States", "Lebanon", "Canada"])]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert plan.selects == {}                       # must NOT pick a country
    assert [f.label for f in unfilled] == ["Country"]


def test_screening_answer_multiword_substring_still_matches():
    artifact = {"screening_answers": [
        {"question": "describe your client-facing experience", "answer": "Years of consulting."},
    ]}
    fields = [FormField(label="Please describe your client-facing experience.", required=True,
                        kind="textarea")]
    plan = build_fill_plan(fields, artifact, APPLICANT)
    assert isinstance(plan, FillPlan)
    assert plan.values["Please describe your client-facing experience."] == "Years of consulting."


def test_eeo_decline_matches_do_not_want_to_answer():
    fields = [FormField(label="Disability Status", required=True, kind="combobox",
                        options=["Yes, I have a disability", "No, I do not have a disability",
                                 "I do not want to answer"])]
    plan = build_fill_plan(fields, {"screening_answers": []}, APPLICANT)
    assert isinstance(plan, FillPlan)
    assert plan.selects["Disability Status"] == "I do not want to answer"


def test_extract_screening_questions_keeps_role_prompts_only():
    fields = [
        FormField(label="First Name", required=True),
        FormField(label="Email", required=True),
        FormField(label="Resume/CV", required=True, kind="file"),
        FormField(label="Cover Letter", required=False, kind="textarea"),
        FormField(label="Why Anthropic?", required=True, kind="textarea"),
        FormField(label="Tell us about a data product you shipped.", required=True, kind="textarea"),
        FormField(label="Do you require visa sponsorship?", required=True, kind="text"),
        FormField(label="LinkedIn Profile", required=True, kind="text"),
        FormField(label="Have you applied to this role in the past 3 months?", required=True, kind="text"),
        FormField(label="AI Policy for Application", required=True, kind="text"),
        FormField(label="(Optional) Personal Preferences", required=False, kind="textarea"),
        FormField(label="When is the earliest you would want to start working with us?", required=True, kind="textarea"),
        FormField(label="Do you have any deadlines or timeline considerations we should be aware of?", required=True, kind="textarea"),
        FormField(label="Gender", required=True, kind="combobox", options=["Decline"]),
    ]
    assert extract_screening_questions(fields) == [
        "Why Anthropic?",
        "Tell us about a data product you shipped.",
    ]


def test_extract_screening_questions_deduplicates_normalized_labels():
    fields = [
        FormField(label="Why Anthropic?", required=True, kind="textarea"),
        FormField(label="  Why   Anthropic? * ", required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == ["Why Anthropic?"]


def test_extract_screening_questions_drops_referral_source_fields():
    # Some ATSs (e.g. Greenhouse) render one "How did you hear about us?" question as a
    # cluster of per-channel text inputs, so the channel name becomes the field label.
    # These are NOT open-ended questions (Twilio #2248 leaked 7 of them, which the
    # generator then "answered" with garbage). Only the real prompt should survive.
    fields = [
        FormField(label="Twitter", required=True, kind="text"),
        FormField(label="Glassdoor", required=True, kind="text"),
        FormField(label="Indeed", required=True, kind="text"),
        FormField(label="Twilio Blog", required=True, kind="text"),
        FormField(label="Conference or Event", required=True, kind="text"),
        FormField(label="Content (e.g. videos, ads, billboards etc)", required=True, kind="text"),
        FormField(label="Other", required=True, kind="text"),
        FormField(label="Why do you want to join Twilio?", required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == ["Why do you want to join Twilio?"]


def test_extract_screening_questions_keeps_short_factual_prompts():
    # Guard against over-blocking: bare education/skill labels we DO ground (School/Degree)
    # must still be generated; only referral channels are dropped.
    fields = [
        FormField(label="School", required=True, kind="text"),
        FormField(label="Degree", required=True, kind="text"),
    ]
    assert extract_screening_questions(fields) == ["School", "Degree"]


def test_extract_screening_questions_keeps_real_questions_that_mention_a_channel():
    # A generic channel word (social media / conference / blog) can appear inside a real
    # screening question phrased as a question/instruction. Those are NOT referral-source
    # cells and must NOT be dropped — the discriminator is question-shape, not length.
    fields = [
        FormField(label="Describe your experience managing social media campaigns.",
                  required=True, kind="textarea"),
        FormField(label="Have you spoken at an industry conference?",
                  required=True, kind="textarea"),
        FormField(label="Tell us about a technical blog post you have written.",
                  required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == [
        "Describe your experience managing social media campaigns.",
        "Have you spoken at an industry conference?",
        "Tell us about a technical blog post you have written.",
    ]


def test_extract_screening_questions_keeps_short_questions_mentioning_a_channel():
    # Short questions that mention a channel word must still be generated — a question is a
    # question regardless of length (the '?'-terminated form is the signal).
    fields = [
        FormField(label="Do you blog?", required=True, kind="textarea"),
        FormField(label="Any conference talks?", required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == ["Do you blog?", "Any conference talks?"]


def test_extract_screening_questions_drops_long_referral_channel_labels():
    # Channel cells aren't always short — some ATSs label them with full phrases. They are
    # source attributions (bare noun phrases, not questions) and must still be dropped, or
    # Claude fabricates prose into a referral input (the Twilio #2248 leak class).
    fields = [
        FormField(label="Conference, meetup, or industry event", required=True, kind="text"),
        FormField(label="Word of mouth from a friend", required=True, kind="text"),
        FormField(label="Social media (Twitter, LinkedIn, etc.)", required=True, kind="text"),
        FormField(label="Why do you want to join us?", required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == ["Why do you want to join us?"]


def test_extract_screening_questions_drops_required_marked_channel_cells():
    # Greenhouse renders required source cells with a trailing '*'. The marker must be
    # stripped before the anchored source-channel match, or 'Other *' / 'Content (...) *'
    # leak through as bogus screening questions.
    fields = [
        FormField(label="Other *", required=True, kind="text"),
        FormField(label="Content (e.g. videos, ads) *", required=True, kind="text"),
    ]
    assert extract_screening_questions(fields) == []


def test_extract_screening_questions_keeps_work_mode_words_manual():
    # remote/hybrid/office stay manual regardless of phrasing. Shape can't separate a groundable
    # experience prompt from an ungroundable work-location preference, and a confabulated
    # preference typed onto a real form is worse than escalating a question to manual — so the
    # conservative drop stays. The interrogative-preference forms here are exactly the leak class
    # a question-shape exception would have reintroduced.
    fields = [
        FormField(label="Describe your experience building remote-first teams.",
                  required=True, kind="textarea"),               # experience-style, still manual
        FormField(label="Are you comfortable working remote?", required=True, kind="text"),
        FormField(label="Are you open to a hybrid schedule?", required=True, kind="text"),
        FormField(label="Are you willing to work in the office full time?",
                  required=True, kind="text"),
        FormField(label="Preferred work arrangement (remote/hybrid/office)",
                  required=True, kind="text"),                   # bare preference cell
    ]
    assert extract_screening_questions(fields) == []


def test_extract_screening_questions_drops_work_auth_and_relocation_questions():
    # Work-auth / visa / relocation are legitimately interrogative but must always stay manual —
    # answered from structured profile data, never the generator. Also guards the relocat\w*
    # boundary fix: the old '\\brelocat\\b' never matched relocate/relocation (the trailing \\b
    # rejects the following word char), so these questions used to leak to the generator.
    fields = [
        FormField(label="Are you authorized to work in the US?", required=True, kind="text"),
        FormField(label="Do you require visa sponsorship?", required=True, kind="text"),
        FormField(label="Are you willing to relocate for this role?", required=True, kind="text"),
        FormField(label="Would you consider relocation?", required=True, kind="text"),
    ]
    assert extract_screening_questions(fields) == []


def test_extract_screening_questions_drops_nonstandard_referral_channels():
    # Faire's "How did you hear about us?" uses channel labels the original vocab missed
    # (billboard, news article, "someone I know personally", technical blogs), so they leaked and
    # got fabricated answers, including a made-up named referral ("Matt referred me"). They are
    # bare-noun source cells, not questions, and must be dropped. Also guards the blog -> blogs?
    # boundary fix (the old \bblog\b never matched "blogs").
    fields = [
        FormField(label="Billboard or outdoor advertising", required=True, kind="text"),
        FormField(label="News article or media coverage", required=True, kind="text"),
        FormField(label="Someone I know personally (friend, family, former colleague)",
                  required=True, kind="text"),
        FormField(label="Faire's technical blogs (Faire.Tech, The Craft)",
                  required=True, kind="text"),
        FormField(label="Why do you want to join Faire?", required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == ["Why do you want to join Faire?"]


def test_extract_screening_questions_keeps_real_questions_mentioning_referral_words():
    # The expanded vocab must not over-block: a real, question-shaped prompt that merely mentions
    # one of those words stays generatable (question-shape exception still applies).
    fields = [
        FormField(label="Have you written a technical blog?", required=True, kind="textarea"),
        FormField(label="Tell us about a mentor or former colleague who shaped your career.",
                  required=True, kind="textarea"),
    ]
    assert extract_screening_questions(fields) == [
        "Have you written a technical blog?",
        "Tell us about a mentor or former colleague who shaped your career.",
    ]


def test_extract_screening_questions_drops_salary_compensation_questions():
    # Comp is a personal decision we never auto-answer; with no salary fact on the profile the
    # generator invented "$140,000 to $160,000 base" (AssemblyAI #2516). Salary / compensation
    # prompts stay manual so the human sets their own number on the live form.
    fields = [
        FormField(label="What is your desired salary for this role?", required=True, kind="text"),
        FormField(label="What are your salary expectations?", required=True, kind="text"),
        FormField(label="Desired compensation", required=True, kind="text"),
    ]
    assert extract_screening_questions(fields) == []


def test_lgbtqia_identity_question_is_dropped_as_eeo():
    # \blgbtq\b never matched "LGBTQIA+" (the trailing \b rejects the following word char — the
    # same boundary trap as relocat/blog), so the identity question leaked to the generator and
    # got auto-answered, disclosing an identity stance. It is EEO and must never be auto-answered.
    q = "Do you consider yourself a member of the LGBTQIA+ community?"
    assert extract_screening_questions([FormField(label=q, kind="textarea")]) == []


def test_self_identification_question_is_dropped_as_eeo():
    # _EEO_RE matched none of the bare self-identification phrasings, so a demographic
    # "I identify as:" prompt leaked to the generator and got auto-answered (Chime #2708,
    # 2026-06-23). It is a self-ID EEO field and must never be auto-answered. Same vocab-gap
    # class as the sex/age/LGBTQIA fixes.
    for q in ["I identify as:", "How do you self-identify?"]:
        assert extract_screening_questions([FormField(label=q, kind="textarea")]) == []


def test_plan_fill_never_types_stored_answer_into_eeo_text_field():
    # Defense in depth behind the generation-time gate: even if a self-ID answer slipped past
    # _EEO_RE and got stored on the draft, the free-text fill branch must not type it into the
    # demographic field. A free-text EEO prompt has no decline option, so a required one
    # escalates to the human rather than disclosing an identity stance.
    artifact = {"cover_letter": "", "screening_answers": [
        {"question": "I identify as:", "answer": "A data professional who connects data to decisions."},
    ]}
    fields = [FormField(label="I identify as:", required=True, kind="textarea")]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert plan.values == {}  # nothing typed into the EEO field
    assert any(f.label == "I identify as:" for f in unfilled)  # escalated to the human


def test_identity_value_maps_github_to_profile_url():
    # A "GitHub" field is an identity/URL field like LinkedIn/website and must be filled from
    # the profile, never answered by the generator (Affirm #2577 typed a prose paragraph into
    # the GitHub field because it had no profile mapping and leaked as a screening question).
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample", email="j@example.com",
                              phone="555-0100", github="https://github.com/patsample")
    assert _identity_value("GitHub", applicant) == "https://github.com/patsample"
    assert _identity_value("GitHub URL", applicant) == "https://github.com/patsample"


def test_github_field_is_not_a_generated_screening_question():
    # GitHub is an admin/identity field — it must never become a generated screening question
    # (else the model writes prose instead of the URL). Same class as linkedin/website/portfolio.
    assert extract_screening_questions([FormField(label="GitHub", kind="text")]) == []


# --- Cover-letter PDF generation for file-upload fields ---------------------

def test_cover_letter_file_upload_generates_pdf():
    artifact = {"cover_letter": "This is my cover letter.\nIt has multiple lines."}
    fields = [FormField(label="Attach", required=True, kind="file", id="cover_letter")]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert "#cover_letter" in plan.files
    assert plan.files["#cover_letter"].endswith(".pdf")
    assert unfilled == []


def test_cover_letter_file_upload_missing_text_escalates():
    fields = [FormField(label="Attach", required=True, kind="file", id="cover_letter")]
    plan, unfilled = plan_fill(fields, {"cover_letter": ""}, APPLICANT)
    assert "#cover_letter" not in plan.files
    assert [f.label for f in unfilled] == ["Attach"]


# --- Combobox fallbacks (country, visa, previously worked) -----------------

def test_combobox_fallback_country_of_residence():
    applicant = ApplicantInfo(
        first_name="Pat", last_name="Sample",
        email="j@example.com", phone="555-555-5555",
        resume_path="data/resume.pdf", country="United States",
    )
    fields = [FormField(
        label="What is your current country of residence?", required=True,
        kind="combobox",
        options=["Afghanistan", "United States of America", "Canada"],
    )]
    plan, unfilled = plan_fill(fields, {"cover_letter": ""}, applicant)
    assert plan.selects == {"What is your current country of residence?": "United States of America"}
    assert unfilled == []


def test_combobox_fallback_visa_sponsorship_defaults_to_no():
    fields = [FormField(
        label="Will you now or in the future require sponsorship?", required=True,
        kind="combobox",
        options=["No", "Yes, H-1B", "Yes, TN"],
    )]
    plan, unfilled = plan_fill(fields, {"cover_letter": ""}, APPLICANT)
    assert plan.selects == {"Will you now or in the future require sponsorship?": "No"}
    assert unfilled == []


def test_combobox_fallback_previously_worked_defaults_to_no():
    fields = [FormField(
        label="Have you previously worked at or consulted for GitLab?", required=True,
        kind="combobox", options=["Yes", "No"],
    )]
    plan, unfilled = plan_fill(fields, {"cover_letter": ""}, APPLICANT)
    assert plan.selects == {"Have you previously worked at or consulted for GitLab?": "No"}
    assert unfilled == []


# --- Skill comboboxes are now included in screening generation -------------

def test_skill_combobox_is_extracted_as_screening_question():
    fields = [FormField(
        label="Do you have strong proficiency in Python?", required=True,
        kind="combobox", options=["Yes", "No"],
    )]
    questions = extract_screening_questions(fields)
    assert questions == ["Do you have strong proficiency in Python?"]


def test_country_combobox_is_not_extracted_as_screening_question():
    fields = [FormField(
        label="What is your current country of residence?", required=True,
        kind="combobox", options=["US", "Canada"],
    )]
    questions = extract_screening_questions(fields)
    assert questions == []   # blocked by _ADMIN_FIELD_RE (country)


def test_maps_linkedin_and_website_from_applicant():
    applicant = ApplicantInfo(
        first_name="Pat", last_name="Sample", email="j@example.com",
        resume_path="data/resume.pdf",
        linkedin="https://example.com/in/pat",
        website="https://example.com",
    )
    fields = [
        FormField(label="LinkedIn Profile", required=False),
        FormField(label="Website", required=False),
        FormField(label="Personal Website / Portfolio", required=False),
    ]
    plan = build_fill_plan(fields, ARTIFACT, applicant)
    assert plan.values["LinkedIn Profile"] == "https://example.com/in/pat"
    assert plan.values["Website"] == "https://example.com"
    assert plan.values["Personal Website / Portfolio"] == "https://example.com"


def test_linkedin_field_not_blank_filled_when_applicant_has_none():
    applicant = ApplicantInfo(first_name="J", last_name="S", email="e",
                              resume_path="data/resume.pdf")
    fields = [FormField(label="LinkedIn Profile", required=False)]
    plan = build_fill_plan(fields, ARTIFACT, applicant)
    assert "LinkedIn Profile" not in plan.values


def test_maps_legal_and_full_name_to_full_name():
    # Ashby labels the name field "Legal Name"; Greenhouse sometimes "Full Name".
    for label in ("Legal Name", "Full Name", "Full legal name", "Name"):
        assert _identity_value(label, APPLICANT) == "Pat Sample", label


def test_preferred_name_is_not_auto_filled():
    # Optional/ambiguous — escalate rather than guess.
    assert _identity_value("Preferred Name (if applicable)", APPLICANT) is None


# --- SP3 Task 2: option-less comboboxes + typeahead escalation ---------------

def test_dynamic_combobox_country_uses_profile():
    applicant = ApplicantInfo(first_name="Pat", last_name="Sample",
                              email="e", phone="5", resume_path="data/resume.pdf",
                              country="United States")
    fields = [FormField(label="Country", required=True, kind="combobox", dynamic_options=True)]  # custom: no options
    plan, unfilled = plan_fill(fields, ARTIFACT, applicant)
    assert plan.selects["Country"] == "United States"
    assert unfilled == []


def test_dynamic_combobox_visa_defaults_no():
    fields = [FormField(label="Do you require visa sponsorship?", required=True, kind="combobox", dynamic_options=True)]
    plan = plan_fill(fields, ARTIFACT, APPLICANT)[0]
    assert plan.selects["Do you require visa sponsorship?"] == "No"


def test_dynamic_combobox_eeo_escalates_never_guesses():
    fields = [FormField(label="Gender", required=True, kind="combobox", dynamic_options=True)]  # custom, no options
    plan, unfilled = plan_fill(fields, ARTIFACT, APPLICANT)
    assert "Gender" not in plan.selects
    assert [f.label for f in unfilled] == ["Gender"]


def test_dynamic_combobox_screening_answer():
    artifact = {"screening_answers": [
        {"question": "Are you authorized to work in the US?", "answer": "Yes"}]}
    fields = [FormField(label="Are you authorized to work in the US?", required=True, kind="combobox", dynamic_options=True)]
    plan = plan_fill(fields, artifact, APPLICANT)[0]
    assert plan.selects["Are you authorized to work in the US?"] == "Yes"


def test_dynamic_combobox_prose_screening_answer_defers_to_planner():
    # A prose screening answer (written for open-text questions) must NOT be jammed into an
    # option-less dropdown value -- it would never match the live Yes/No list (this is what
    # made the live DoorDash apply type paragraphs into dropdowns). plan_fill leaves the field
    # unfilled so the LLM planner can derive the short option ("Yes") from the same prose.
    q = "Do you have 4+ years of SQL experience?"
    artifact = {"screening_answers": [
        {"question": q,
         "answer": "Yes, SQL has been a core part of my work for well over four years "
                   "across industries and tool stacks, including at Fortune Brands."}]}
    fields = [FormField(label=q, required=True, kind="combobox", dynamic_options=True)]
    plan, unfilled = plan_fill(fields, artifact, APPLICANT)
    assert q not in plan.selects                       # prose NOT used as the select value
    assert [f.label for f in unfilled] == [q]          # deferred to the planner


def test_dynamic_combobox_short_screening_answer_still_used():
    # A SHORT option-like screening answer ("Yes") is still used directly (no planner needed).
    q = "Are you authorized to work in the US?"
    artifact = {"screening_answers": [{"question": q, "answer": "Yes"}]}
    fields = [FormField(label=q, required=True, kind="combobox", dynamic_options=True)]
    plan = plan_fill(fields, artifact, APPLICANT)[0]
    assert plan.selects[q] == "Yes"


def test_dynamic_combobox_unknown_escalates():
    fields = [FormField(label="Preferred start date bucket", required=True, kind="combobox", dynamic_options=True)]
    plan, unfilled = plan_fill(fields, ARTIFACT, APPLICANT)
    assert "Preferred start date bucket" not in plan.selects
    assert [f.label for f in unfilled] == ["Preferred start date bucket"]


def test_empty_options_combobox_without_dynamic_flag_escalates():
    # A Playwright combobox whose options couldn't be read (empty, dynamic_options=False) must
    # still ESCALATE to the human, exactly as before SP3 — never silently best-guessed.
    fields = [FormField(label="Country", required=True, kind="combobox")]  # no options, not dynamic
    plan, unfilled = plan_fill(fields, ARTIFACT, APPLICANT)
    assert "Country" not in plan.selects
    assert [f.label for f in unfilled] == ["Country"]


def test_typeahead_escalates_never_filled():
    fields = [FormField(label="School", required=True, kind="typeahead")]
    plan, unfilled = plan_fill(fields, ARTIFACT, APPLICANT)
    assert plan.selects == {} and plan.values == {}
    assert [f.label for f in unfilled] == ["School"]


def test_native_combobox_with_options_unchanged():
    artifact = {"screening_answers": [
        {"question": "Are you authorized to work in the US?", "answer": "Yes"}]}
    fields = [FormField(label="Are you authorized to work in the US?", required=True,
                        kind="combobox", options=["Yes", "No"])]
    plan = plan_fill(fields, artifact, APPLICANT)[0]
    assert plan.selects["Are you authorized to work in the US?"] == "Yes"


def test_mapped_typeahead_eeo_still_escalates():
    # An EEO React-Select now arrives as a dynamic_options combobox (not typeahead);
    # _dynamic_combobox_value must still refuse to guess a demographic -> unfilled.
    fields = [FormField(label="Gender", required=True, kind="combobox", dynamic_options=True)]
    plan, unfilled = plan_fill(fields, {"screening_answers": []}, APPLICANT)
    assert fields[0] in unfilled
    assert plan.selects == {}


def test_mapped_typeahead_consent_still_escalates():
    # A consent/acknowledgement React-Select (no screening answer, no deterministic fact)
    # stays unfilled rather than auto-filling.
    fields = [FormField(label="I acknowledge the terms and conditions", required=True,
                        kind="combobox", dynamic_options=True)]
    plan, unfilled = plan_fill(fields, {"screening_answers": []}, APPLICANT)
    assert fields[0] in unfilled
    assert plan.selects == {}


def test_planner_eligible_skill_screener():
    from backend.platforms.form_fill import is_planner_eligible
    assert is_planner_eligible(
        FormField(label="Years of Python experience", kind="combobox", dynamic_options=True))
    assert is_planner_eligible(
        FormField(label="Are you authorized to work in the US?", kind="combobox"))


def test_planner_ineligible_eeo_and_consent():
    from backend.platforms.form_fill import is_planner_eligible
    assert not is_planner_eligible(
        FormField(label="Gender", kind="combobox", dynamic_options=True))
    assert not is_planner_eligible(FormField(label="Veteran status", kind="combobox"))
    assert not is_planner_eligible(
        FormField(label="I acknowledge the terms and conditions", kind="combobox",
                  dynamic_options=True))
    assert not is_planner_eligible(
        FormField(label="Do you consent to a background check?", kind="combobox"))


def test_planner_ineligible_non_dropdown():
    from backend.platforms.form_fill import is_planner_eligible
    assert not is_planner_eligible(FormField(label="Cover letter", kind="textarea"))
    assert not is_planner_eligible(FormField(label="Resume", kind="file"))
    assert not is_planner_eligible(FormField(label="First Name", kind="text"))


def test_planner_ineligible_identity_demographics():
    # LGBTQ-identity demographics must be HARD-BLOCKED from the LLM planner (safety invariant:
    # identity never reaches the model). Regression for the final-review C1 finding.
    from backend.platforms.form_fill import is_planner_eligible
    for label in ("Sexual orientation", "Are you transgender?", "Pronouns",
                  "Preferred pronouns", "Do you identify as LGBTQ?"):
        assert not is_planner_eligible(
            FormField(label=label, kind="combobox", dynamic_options=True)), label


def test_planner_eligibility_consent_regex_precision():
    from backend.platforms.form_fill import is_planner_eligible
    # noun/verb consent forms are HARD-BLOCKED (never reach the model)
    assert not is_planner_eligible(
        FormField(label="Electronic signature acknowledgement", kind="combobox"))
    assert not is_planner_eligible(FormField(label="Candidate acknowledgement", kind="combobox"))
    assert not is_planner_eligible(
        FormField(label="I certify that my answers are accurate", kind="combobox"))
    assert not is_planner_eligible(
        FormField(label="I agree to the privacy policy", kind="combobox"))
    # legitimate screeners that merely contain terms/conditions/certification stay ELIGIBLE
    assert is_planner_eligible(FormField(label="Payment terms preference", kind="combobox"))
    assert is_planner_eligible(FormField(label="Working conditions preference", kind="combobox"))
    assert is_planner_eligible(FormField(label="AWS Certification level", kind="combobox"))
