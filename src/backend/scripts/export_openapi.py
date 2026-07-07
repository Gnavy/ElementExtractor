#!/usr/bin/env python3
"""导出 OpenAPI JSON（含 v1 API Key 安全定义）。"""

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent.parent
OUTPUT = REPO_ROOT / "docs" / "openapi-v1.json"


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.main import app

    schema = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
