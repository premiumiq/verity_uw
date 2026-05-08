"""Verity Studio Web Application Factory.

Creates a FastAPI sub-application for Verity Studio — the authoring
and governance frontend for non-developer users.

Studio is a sibling to the Admin web app (see ``app.py``). Both are
mounted by the standalone Verity server (``verity/main.py``):

    /admin/    — read-mostly operational console (existing)
    /studio/   — authoring environment (this file)

Both share the same FastAPI process, the same database, and the same
``/api/v1/*`` REST API surface. Studio introduces no parallel write
paths — every authoring action ultimately calls a ``/api/v1/*``
endpoint that the SDK and CLI also use.

Information architecture (see docs/plans/studio-build-plan.md §2.2):

    Compose   — author packages (agents, tasks, prompts, tools, configs)
    Validate  — preview, test, run validation batches
    Deploy    — drive lifecycle (promote, rollback, diff)
    Govern    — approvals inbox, audit trail, redundancy review, policies

Usage:
    from verity.web.studio_app import create_verity_studio

    verity = Verity(database_url="...")
    studio_app = create_verity_studio(verity)
    main_app.mount("/studio", studio_app)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from verity.web.middleware.persona import PersonaMiddleware
from verity.web.studio_routes import create_studio_routes


# Studio reuses the same templates and static directories as the
# Admin app — the templates/ tree has a ``studio/`` subfolder for
# Studio-specific pages, and verity.css is shared because Studio uses
# the same Verity brand chrome as the Admin console.
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_verity_studio(verity) -> FastAPI:
    """Create the Verity Studio web UI as a FastAPI sub-application.

    Args:
        verity: An initialized Verity SDK client instance.

    Returns:
        A FastAPI app with all Studio page routes and static file
        serving. The caller mounts it at ``/studio`` on the main app.
    """
    app = FastAPI(
        title="Verity Studio",
        # Studio is an HTML UI, not a JSON API — hide Swagger/Redoc.
        docs_url=None,
        redoc_url=None,
    )

    # Serve static files (verity.css, fonts, etc.) at /studio/static/.
    # Templates reference these via absolute paths like
    # /studio/static/verity.css.
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="studio-static",
    )

    # Persona middleware reads the vty_persona cookie and stashes the
    # parsed StudioRole on request.state.persona for templates and
    # route handlers. Mounted only on Studio (not Admin or the JSON
    # API). See verity/src/verity/web/middleware/persona.py.
    app.add_middleware(PersonaMiddleware)

    # Register all HTML page routes.
    router = create_studio_routes(verity, templates_dir=str(TEMPLATES_DIR))
    app.include_router(router)

    return app
