# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "httpx2[http2,brotli,zstd]", "typer>=0.12,<0.20", "click<8.2",
#   "rich", "pydantic", "tzdata",
# ]
# ///
"""Weather forecasts and airport observations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from weather_live import main

if __name__ == "__main__":
    raise SystemExit(main())
