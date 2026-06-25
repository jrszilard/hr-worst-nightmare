"""Seed the database with realistic Upwork contracts for development.

Usage:
    python scripts/seed_test_data.py

Uses the existing SQLAlchemy async setup to write to the database.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path so ``backend`` is importable.
_project_root = str(Path(__file__).resolve().parents[1])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Set dummy env vars when running outside of a configured environment
# (e.g. no .env file). Real values are only needed for AI calls.
os.environ.setdefault("ANTHROPIC_API_KEY", "seed-script-placeholder")

from backend.core.enums import ContractStatus, ContractType  # noqa: E402
from backend.db.database import async_session, create_tables  # noqa: E402
from backend.db.models import ContractDB  # noqa: E402

# ── Seed data ────────────────────────────────────────────────────────────────

_NOW = datetime.now(UTC)

CONTRACTS: list[dict] = [
    # ── Power BI / dashboard projects ──────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-pbi-exec-dash",
        "url": "https://www.upwork.com/jobs/~seed-pbi-exec-dash",
        "title": "Executive KPI Dashboard in Power BI",
        "description": (
            "We need an experienced Power BI developer to build a multi-page "
            "executive dashboard. The data lives in Azure SQL and is refreshed "
            "daily via an existing ETL pipeline. Key KPIs include revenue, "
            "churn rate, customer acquisition cost, and NPS. Must use DAX "
            "for custom measures and RLS for role-based security."
        ),
        "skills_required": ["Power BI", "DAX", "SQL", "Data modeling", "Azure SQL"],
        "budget_min": 3000.0,
        "budget_max": 8000.0,
        "contract_type": ContractType.fixed,
        "duration": "2-4 weeks",
        "proposals_count": 12,
        "client_hire_rate": 0.85,
        "client_total_spent": 45000.0,
        "client_location": "United States",
        "match_score": 0.95,
        "roi_score": 18.5,
        "connects_cost": 8,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=6),
    },
    {
        "platform": "upwork",
        "external_id": "seed-pbi-sales",
        "url": "https://www.upwork.com/jobs/~seed-pbi-sales",
        "title": "Power BI Sales Pipeline Dashboard",
        "description": (
            "Looking for a Power BI expert to create a sales pipeline dashboard "
            "pulling from Salesforce. Need to visualize deal stages, close rates, "
            "revenue forecasts, and rep performance comparisons."
        ),
        "skills_required": ["Power BI", "DAX", "Salesforce", "SQL"],
        "budget_min": 1500.0,
        "budget_max": 4000.0,
        "contract_type": ContractType.fixed,
        "duration": "1-2 weeks",
        "proposals_count": 8,
        "client_hire_rate": 0.72,
        "client_total_spent": 22000.0,
        "client_location": "Canada",
        "match_score": 0.88,
        "roi_score": 12.3,
        "connects_cost": 6,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=12),
    },

    # ── Tableau projects ──────────────────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-tableau-health",
        "url": "https://www.upwork.com/jobs/~seed-tableau-health",
        "title": "Healthcare Analytics Tableau Dashboard",
        "description": (
            "We are a mid-size hospital network seeking a Tableau developer to "
            "build patient flow and operational dashboards. Data sits in "
            "Snowflake. Need calculated fields, parameters, and drill-down "
            "capabilities. HIPAA awareness preferred."
        ),
        "skills_required": ["Tableau", "SQL", "Data modeling", "Snowflake"],
        "budget_min": 5000.0,
        "budget_max": 15000.0,
        "contract_type": ContractType.fixed,
        "duration": "4-8 weeks",
        "proposals_count": 18,
        "client_hire_rate": 0.90,
        "client_total_spent": 120000.0,
        "client_location": "United States",
        "match_score": 0.82,
        "roi_score": 22.1,
        "connects_cost": 10,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=1),
    },
    {
        "platform": "upwork",
        "external_id": "seed-tableau-ecomm",
        "url": "https://www.upwork.com/jobs/~seed-tableau-ecomm",
        "title": "E-commerce Reporting Suite — Tableau",
        "description": (
            "Build a Tableau reporting suite for our Shopify store. Need to "
            "track revenue by product, customer cohorts, marketing attribution, "
            "and inventory levels. Data is in BigQuery."
        ),
        "skills_required": ["Tableau", "SQL", "BigQuery", "Data analysis"],
        "budget_min": 40.0,
        "budget_max": 75.0,
        "contract_type": ContractType.hourly,
        "duration": "1-3 months",
        "proposals_count": 22,
        "client_hire_rate": 0.65,
        "client_total_spent": 8500.0,
        "client_location": "United Kingdom",
        "match_score": 0.78,
        "roi_score": 8.7,
        "connects_cost": 6,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=2),
    },

    # ── ETL / data pipeline projects ──────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-etl-pipeline",
        "url": "https://www.upwork.com/jobs/~seed-etl-pipeline",
        "title": "Python ETL Pipeline — API to Data Warehouse",
        "description": (
            "We need a Python developer to build an automated ETL pipeline that "
            "pulls data from 3 REST APIs (Stripe, HubSpot, Google Analytics), "
            "transforms it, and loads into our PostgreSQL data warehouse. Should "
            "run daily via cron or Airflow."
        ),
        "skills_required": ["Python", "ETL", "REST APIs", "PostgreSQL", "Pandas"],
        "budget_min": 4000.0,
        "budget_max": 10000.0,
        "contract_type": ContractType.fixed,
        "duration": "2-4 weeks",
        "proposals_count": 30,
        "client_hire_rate": 0.78,
        "client_total_spent": 55000.0,
        "client_location": "Germany",
        "match_score": 0.90,
        "roi_score": 14.2,
        "connects_cost": 12,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=18),
    },
    {
        "platform": "upwork",
        "external_id": "seed-etl-migration",
        "url": "https://www.upwork.com/jobs/~seed-etl-migration",
        "title": "Database Migration & ETL Optimization",
        "description": (
            "Migrate our legacy MySQL database to PostgreSQL and optimize "
            "existing ETL scripts. Current pipeline takes 4 hours — need it "
            "under 30 minutes. About 50 tables, 200M rows total."
        ),
        "skills_required": ["Python", "SQL", "ETL", "Database design", "PostgreSQL"],
        "budget_min": 8000.0,
        "budget_max": 20000.0,
        "contract_type": ContractType.fixed,
        "duration": "4-6 weeks",
        "proposals_count": 15,
        "client_hire_rate": 0.82,
        "client_total_spent": 78000.0,
        "client_location": "United States",
        "match_score": 0.85,
        "roi_score": 25.0,
        "connects_cost": 10,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=1, hours=6),
    },

    # ── AI / LLM integration projects ─────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-ai-chatbot",
        "url": "https://www.upwork.com/jobs/~seed-ai-chatbot",
        "title": "AI Customer Support Chatbot with RAG",
        "description": (
            "Build an AI-powered customer support chatbot using RAG "
            "(Retrieval-Augmented Generation). It should ingest our knowledge "
            "base (Notion pages, PDFs), embed them, and answer questions "
            "accurately. Must use Claude or GPT-4 with vector search."
        ),
        "skills_required": ["Python", "LangChain", "Anthropic Claude API", "RAG pipelines"],
        "budget_min": 10000.0,
        "budget_max": 25000.0,
        "contract_type": ContractType.fixed,
        "duration": "4-8 weeks",
        "proposals_count": 45,
        "client_hire_rate": 0.60,
        "client_total_spent": 15000.0,
        "client_location": "Australia",
        "match_score": 0.92,
        "roi_score": 10.8,
        "connects_cost": 16,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=3),
    },
    {
        "platform": "upwork",
        "external_id": "seed-ai-agent",
        "url": "https://www.upwork.com/jobs/~seed-ai-agent",
        "title": "LLM Agent for Automated Report Generation",
        "description": (
            "We want an AI agent that can pull data from our APIs, generate "
            "weekly business reports in PDF format, and email them to "
            "stakeholders. Should use function calling and be able to handle "
            "follow-up questions."
        ),
        "skills_required": ["Python", "AI agents", "OpenAI API", "REST APIs", "Process automation"],
        "budget_min": 75.0,
        "budget_max": 125.0,
        "contract_type": ContractType.hourly,
        "duration": "3-6 months",
        "proposals_count": 38,
        "client_hire_rate": 0.70,
        "client_total_spent": 32000.0,
        "client_location": "United States",
        "match_score": 0.88,
        "roi_score": 15.5,
        "connects_cost": 12,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=8),
    },
    {
        "platform": "upwork",
        "external_id": "seed-ai-rag-docs",
        "url": "https://www.upwork.com/jobs/~seed-ai-rag-docs",
        "title": "Internal Documentation Search with RAG Pipeline",
        "description": (
            "Build a RAG-based internal search tool that lets employees query "
            "our Confluence docs using natural language. Need embeddings, "
            "vector DB (Pinecone or Weaviate), and a simple Streamlit UI."
        ),
        "skills_required": ["Python", "RAG pipelines", "LangChain", "Anthropic Claude API"],
        "budget_min": 6000.0,
        "budget_max": 12000.0,
        "contract_type": ContractType.fixed,
        "duration": "3-5 weeks",
        "proposals_count": 25,
        "client_hire_rate": 0.75,
        "client_total_spent": 42000.0,
        "client_location": "Canada",
        "match_score": 0.93,
        "roi_score": 16.2,
        "connects_cost": 10,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=1, hours=2),
    },

    # ── Python scripting / data analysis (adjacent) ───────────────────
    {
        "platform": "upwork",
        "external_id": "seed-python-scrape",
        "url": "https://www.upwork.com/jobs/~seed-python-scrape",
        "title": "Web Scraper for Competitor Pricing Data",
        "description": (
            "Need a Python script to scrape pricing data from 5 competitor "
            "websites daily and store results in a Google Sheet. Must handle "
            "anti-bot measures and rotating proxies."
        ),
        "skills_required": ["Python", "Web scraping", "Automation"],
        "budget_min": 500.0,
        "budget_max": 1500.0,
        "contract_type": ContractType.fixed,
        "duration": "1 week",
        "proposals_count": 50,
        "client_hire_rate": 0.55,
        "client_total_spent": 3200.0,
        "client_location": "India",
        "match_score": 0.52,
        "roi_score": 2.1,
        "connects_cost": 4,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=3),
    },
    {
        "platform": "upwork",
        "external_id": "seed-data-analysis",
        "url": "https://www.upwork.com/jobs/~seed-data-analysis",
        "title": "Data Analysis & Visualization — Marketing Campaign Results",
        "description": (
            "We need a data analyst to crunch the numbers on our last 3 "
            "marketing campaigns. Deliverables: a Jupyter notebook with EDA, "
            "visualizations (matplotlib/seaborn), and a brief written summary."
        ),
        "skills_required": ["Python", "Pandas", "Data analysis", "Jupyter"],
        "budget_min": 800.0,
        "budget_max": 2000.0,
        "contract_type": ContractType.fixed,
        "duration": "1-2 weeks",
        "proposals_count": 35,
        "client_hire_rate": 0.68,
        "client_total_spent": 12000.0,
        "client_location": "Netherlands",
        "match_score": 0.65,
        "roi_score": 4.5,
        "connects_cost": 6,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=2, hours=8),
    },

    # ── General data science ──────────────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-ds-churn",
        "url": "https://www.upwork.com/jobs/~seed-ds-churn",
        "title": "Customer Churn Prediction Model",
        "description": (
            "Build a machine learning model to predict customer churn for our "
            "SaaS product. We have 2 years of usage data (~50k customers). "
            "Deliverables: trained model, feature importance analysis, and "
            "a brief technical report."
        ),
        "skills_required": ["Python", "General data science", "Pandas", "Machine Learning"],
        "budget_min": 3000.0,
        "budget_max": 8000.0,
        "contract_type": ContractType.fixed,
        "duration": "2-3 weeks",
        "proposals_count": 40,
        "client_hire_rate": 0.62,
        "client_total_spent": 18000.0,
        "client_location": "Sweden",
        "match_score": 0.55,
        "roi_score": 5.8,
        "connects_cost": 10,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=1, hours=18),
    },

    # ── Low-budget / high-competition contract (red indicator) ────────
    {
        "platform": "upwork",
        "external_id": "seed-low-budget",
        "url": "https://www.upwork.com/jobs/~seed-low-budget",
        "title": "Simple Excel to CSV Conversion Script",
        "description": (
            "Need a quick Python script to convert 10 Excel files into CSVs "
            "with some basic data cleaning. Very straightforward."
        ),
        "skills_required": ["Python", "Pandas"],
        "budget_min": 50.0,
        "budget_max": 150.0,
        "contract_type": ContractType.fixed,
        "duration": "Less than 1 week",
        "proposals_count": 48,
        "client_hire_rate": 0.40,
        "client_total_spent": 800.0,
        "client_location": "Philippines",
        "match_score": 0.35,
        "roi_score": 0.3,
        "connects_cost": 2,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(days=4),
    },

    # ── High-value hourly contract ────────────────────────────────────
    {
        "platform": "upwork",
        "external_id": "seed-hourly-bi",
        "url": "https://www.upwork.com/jobs/~seed-hourly-bi",
        "title": "Ongoing Power BI Consultant — FinTech Startup",
        "description": (
            "We are a fast-growing FinTech startup looking for an ongoing "
            "Power BI consultant. You will build and maintain dashboards for "
            "our product, finance, and ops teams. 20-30 hrs/week to start. "
            "Must be available for daily standups (EST)."
        ),
        "skills_required": ["Power BI", "DAX", "SQL", "Data modeling"],
        "budget_min": 100.0,
        "budget_max": 150.0,
        "contract_type": ContractType.hourly,
        "duration": "6+ months",
        "proposals_count": 5,
        "client_hire_rate": 0.92,
        "client_total_spent": 250000.0,
        "client_location": "United States",
        "match_score": 0.97,
        "roi_score": 50.0,
        "connects_cost": 8,
        "status": ContractStatus.new,
        "posted_at": _NOW - timedelta(hours=2),
    },
]

async def seed() -> None:
    """Create tables and insert seed data. Safe to re-run (upserts by unique keys)."""
    await create_tables()

    async with async_session() as session:
        # ── Seed contracts (upsert by platform + external_id) ────────
        for data in CONTRACTS:
            from sqlalchemy import select
            existing = await session.execute(
                select(ContractDB).where(
                    ContractDB.platform == data["platform"],
                    ContractDB.external_id == data["external_id"],
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(ContractDB(**data))

        await session.commit()

    count = len(CONTRACTS)
    print(f"Seeded {count} contracts.")


if __name__ == "__main__":
    asyncio.run(seed())
