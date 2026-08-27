"""Entry point: `python -m services.render_service`"""
import os
import uvicorn

from .server import build_app


def main() -> None:
    scaffold_url = os.getenv("RENDER_SCAFFOLD_URL", "http://localhost:6503")
    port = int(os.getenv("RENDER_SERVICE_PORT", "6502"))
    uvicorn.run(build_app(scaffold_url=scaffold_url), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
