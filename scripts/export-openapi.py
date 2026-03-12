#!/usr/bin/env python3
# Copyright 2025 ByBren, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Export the OpenAPI JSON spec from the FastAPI application.

Usage:
    python scripts/export-openapi.py

Outputs the spec to docs/api/openapi.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure environment is set for standalone execution (avoids production
# validation errors when no .env file is present).
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Add project root to sys.path so ``core`` is importable when running
# the script from the repository root.
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.main import create_app  # noqa: E402

OUTPUT_DIR = _project_root / "docs" / "api"
OUTPUT_FILE = OUTPUT_DIR / "openapi.json"


def main() -> None:
    """Generate and write the OpenAPI specification."""
    app = create_app()
    spec = app.openapi()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w") as f:
        json.dump(spec, f, indent=2)
        f.write("\n")  # trailing newline

    print(f"OpenAPI spec written to {OUTPUT_FILE}")  # noqa: T201


if __name__ == "__main__":
    main()
