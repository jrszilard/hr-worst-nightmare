from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    ANTHROPIC_API_KEY: str
    # Per-person profile bundle. All per-user paths resolve under this directory.
    # Relative values resolve against the project root. Default `data` keeps the
    # existing instance + tests working; the public template sets `profile`.
    PROFILE_DIR: str = "data"
    # When empty, ProfileContext derives a sqlite URL under PROFILE_DIR.
    DATABASE_URL: str = ""
    CHROME_MCP_URL: str = "http://localhost:9222"
    # Browser engine selection (Track B). Default reproduces today's Playwright apply.
    BROWSER_ENGINE: str = "playwright"
    BROWSER_MODE: str = "launch"  # launch | cdp
    # ai-in-browser engine (BROWSER_ENGINE=aiinbrowser). Empty repo path -> the
    # factory resolves the sibling ai-projects/ai-in-browser checkout.
    AIINBROWSER_REPO: str = ""
    AIINBROWSER_CONNECT_MS: int = 35000
    CORS_ORIGINS: str = "http://localhost:5173"
    JSEARCH_API_KEY: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
