"""Tests for backend.onboarding.ingest — robust, never-raising input readers."""

import httpx
import pytest
from reportlab.pdfgen import canvas

from backend.onboarding import ingest


def _make_pdf(path, text):
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, text)
    c.save()


def test_read_resume_text_extracts_pdf(tmp_path):
    pdf = tmp_path / "resume.pdf"
    _make_pdf(pdf, "Pat Sample Data Engineer Python SQL")
    text = ingest.read_resume_text(pdf)
    assert "Pat Sample" in text


def test_read_resume_text_missing_file_returns_empty(tmp_path):
    assert ingest.read_resume_text(tmp_path / "nope.pdf") == ""


def test_read_links_parses_one_per_line(tmp_path):
    f = tmp_path / "links.txt"
    f.write_text("https://example.com\n\nhttps://example.com/in/pat\n", encoding="utf-8")
    assert ingest.read_links(f) == ["https://example.com", "https://example.com/in/pat"]


def test_fetch_url_returns_text_on_200():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="<html><body>Hi there</body></html>"))
    client = httpx.Client(transport=transport)
    out = ingest.fetch_url("https://example.com", client=client)
    assert "Hi there" in out


def test_fetch_url_degrades_on_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(999))
    client = httpx.Client(transport=transport)
    assert ingest.fetch_url("https://blocked.example", client=client) == ""


def test_read_work_samples_reads_text_files(tmp_path):
    d = tmp_path / "work-samples"
    d.mkdir()
    (d / "a.md").write_text("# Project A\nBuilt a pipeline.", encoding="utf-8")
    (d / "b.txt").write_text("Project B notes", encoding="utf-8")
    samples = ingest.read_work_samples(d)
    names = {name for name, _ in samples}
    assert names == {"a.md", "b.txt"}
