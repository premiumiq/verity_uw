"""Verity Web Application Factory.

Creates a FastAPI sub-application for the Verity admin web UI.
This is mounted by the consuming app (e.g., UW Demo) at /admin/.

Usage:
    from verity.web.app import create_verity_web

    verity = Verity(database_url="...")
    web_app = create_verity_web(verity)
    main_app.mount("/admin", web_app)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from verity.web.routes import create_routes


# Path to the templates and static directories
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_verity_web(verity) -> FastAPI:
    """Create the Verity admin web UI as a FastAPI sub-application.

    Args:
        verity: An initialized Verity SDK client instance.

    Returns:
        A FastAPI app with all admin UI routes and static file serving.
    """
    app = FastAPI(
        title="Verity Admin",
        docs_url=None,      # No Swagger UI for the web app
        redoc_url=None,
    )

    # Serve static files (verity.css) at /static/
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="verity-static")

    # Register all HTML page routes
    router = create_routes(verity, templates_dir=str(TEMPLATES_DIR))
    app.include_router(router)

    return app
