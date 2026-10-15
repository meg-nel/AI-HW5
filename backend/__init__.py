from pathlib import Path

from dotenv import load_dotenv

# Load ANTHROPIC_API_KEY (and any CAMPUS_CUSTOMS_* overrides) from the project's .env file.
# .env is gitignored, so the key never ends up on GitHub.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
