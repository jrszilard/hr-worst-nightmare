"""Gated: AiInBrowserEngine honors the SAME op contract, in real Brave.

Run with the ai-in-browser extension loaded in Brave:
    .venv/bin/python -m pytest -m aiinbrowser -q
Serves the conformance fixture over http (the extension injects only on http(s)),
then drives the engine through the shared op-contract assertions.
"""

import functools
import http.server
import pathlib
import threading

import pytest

from backend.config import settings
from backend.platforms.browser.aiinbrowser_engine import AiInBrowserEngine
from tests.test_engine_conformance import assert_honors_op_contract

_FORMS = pathlib.Path(__file__).parent / "fixtures" / "forms"


@pytest.mark.aiinbrowser
async def test_aiinbrowser_honors_op_contract():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(_FORMS))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/sample_apply.html"
        repo = settings.AIINBROWSER_REPO or str(
            pathlib.Path(__file__).resolve().parents[1].parent / "ai-in-browser"
        )
        engine = AiInBrowserEngine(repo=repo, connect_ms=settings.AIINBROWSER_CONNECT_MS)
        await assert_honors_op_contract(engine, url)
    finally:
        server.shutdown()
        server.server_close()
