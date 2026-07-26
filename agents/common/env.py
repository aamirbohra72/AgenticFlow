"""Load environment variables from the repo-root .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

if key := os.getenv("MISTRAL_API_KEY"):
    os.environ["MISTRAL_API_KEY"] = key

# Disable CrewAI cloud tracing/telemetry (breaks on some Windows setups)
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("CREWAI_TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
