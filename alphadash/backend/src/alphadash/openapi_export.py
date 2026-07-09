"""Export the OpenAPI spec (S1.9): `uv run python -m alphadash.openapi_export [out.json]`.

The frontend generates its client types from this via `npm run gen:api` — the spec file is the
contract artifact, regenerated whenever endpoints change.
"""

from __future__ import annotations

import json
import sys

from alphadash.config import Settings
from alphadash.main import create_app


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "../frontend/openapi.json"
    app = create_app(Settings(database_url="sqlite://", providers="stub"))
    with open(out, "w") as f:
        json.dump(app.openapi(), f, indent=1)
    print(f"OpenAPI spec written to {out}")


if __name__ == "__main__":
    main()
