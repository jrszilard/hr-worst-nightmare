"""Shared enums for the contract-finder project.

These enums use ``str, enum.Enum`` as their base so they work transparently
with both SQLAlchemy (which stores the string value in the DB) and Pydantic
(which serialises/deserialises them as strings).
"""

import enum


class ContractStatus(str, enum.Enum):
    new = "new"
    reviewed = "reviewed"
    drafting = "drafting"
    applied = "applied"
    skipped = "skipped"


class ContractType(str, enum.Enum):
    hourly = "hourly"
    fixed = "fixed"


class ProposalStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    submitted = "submitted"


class ApplicationOutcome(str, enum.Enum):
    submitted = "submitted"
    viewed = "viewed"
    interview = "interview"
    hired = "hired"
    rejected = "rejected"
    no_response = "no_response"


class ProposalSectionType(str, enum.Enum):
    hook = "hook"
    experience = "experience"
    approach = "approach"
    differentiator = "differentiator"
    cta = "cta"


class ScannerState(str, enum.Enum):
    idle = "idle"
    running = "running"
    complete = "complete"
    error = "error"


class PreferredDuration(str, enum.Enum):
    short = "short"
    medium = "medium"
    long = "long"
    any = "any"


class PreferredContractType(str, enum.Enum):
    hourly = "hourly"
    fixed = "fixed"
    both = "both"


class OpportunityKind(str, enum.Enum):
    contract = "contract"
    job = "job"


class SubmissionChannel(str, enum.Enum):
    direct = "direct"
    browser = "browser"
    auto = "auto"
    external = "external"


class BudgetPeriod(str, enum.Enum):
    week = "week"


class SpendKind(str, enum.Enum):
    connects = "connects"
    generation = "generation"
    generation_dollars = "generation_dollars"
