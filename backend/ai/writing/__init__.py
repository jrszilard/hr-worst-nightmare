"""Reusable writing-quality layer: style rules, sanitizer, injection scan, critic, pipeline."""

from backend.ai.writing.injection import TrapFlag, scan_for_traps
from backend.ai.writing.pipeline import WritingReport, run_writing_pipeline
from backend.ai.writing.sanitizer import SanitizerReport, sanitize
from backend.ai.writing.style import STYLE_RULES, style_rules_text

__all__ = [
    "TrapFlag", "scan_for_traps",
    "WritingReport", "run_writing_pipeline",
    "SanitizerReport", "sanitize",
    "STYLE_RULES", "style_rules_text",
]
