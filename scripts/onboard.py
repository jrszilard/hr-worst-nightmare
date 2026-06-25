"""Generate a draft profile bundle from PROFILE_DIR/inputs/.

    PYTHONPATH=. python scripts/onboard.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ai.usage import collect_usage  # noqa: E402
from backend.core.profile_context import get_profile_context  # noqa: E402
from backend.onboarding import run_onboarding  # noqa: E402


async def main() -> None:
    ctx = get_profile_context()
    if not ctx.inputs_dir.exists():
        print(f"No inputs dir at {ctx.inputs_dir}. Create it and add resume.pdf / links.txt / work-samples/.")
        return
    print(f"Onboarding from {ctx.inputs_dir} ...")
    with collect_usage() as acc:
        await run_onboarding(ctx)
    print(f"Wrote {ctx.profile_yaml}")
    print(f"Review: {ctx.onboarding_report}")
    print(f"Extraction cost: ${acc.cost_usd()}")


if __name__ == "__main__":
    asyncio.run(main())
