from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("digestor.web:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
