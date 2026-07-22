"""Load environment variables from the repo-root .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

if key := os.getenv("MISTRAL_API_KEY"):
    os.environ["MISTRAL_API_KEY"] = key
