"""Verity CLI entry points.

Usage:
    verity init     — Create database and apply schema
    verity serve    — Run API server
    verity web      — Run web UI (API + admin interface)
    verity setup    — Generate infrastructure configs
"""

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="verity",
        description="Verity — AI Trust & Compliance Framework",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # verity init
    init_parser = subparsers.add_parser("init", help="Create database and apply schema")
    init_parser.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    init_parser.add_argument("--drop-existing", action="store_true", help="Drop and recreate all tables")

    # verity serve
    serve_parser = subparsers.add_parser("serve", help="Run Verity API server")
    serve_parser.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8001, help="Bind port")

    # verity web
    web_parser = subparsers.add_parser("web", help="Run Verity web UI (API + admin)")
    web_parser.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    web_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    web_parser.add_argument("--port", type=int, default=8001, help="Bind port")

    # verity setup
    setup_parser = subparsers.add_parser("setup", help="Generate infrastructure configs")
    setup_parser.add_argument("--target", choices=["docker", "k8s"], required=True)
    setup_parser.add_argument("--output", default=".", help="Output directory")

    # verity compliance ...
    compliance_parser = subparsers.add_parser(
        "compliance", help="Compliance metamodel operations (seed, show)"
    )
    compliance_sub = compliance_parser.add_subparsers(
        dest="compliance_action", help="Compliance action"
    )

    seed_static_parser = compliance_sub.add_parser(
        "seed-static",
        help="Seed frameworks, themes, and feature hierarchy from compliance_seed_static.yaml",
    )
    seed_static_parser.add_argument("--database-url", required=True)

    show_parser = compliance_sub.add_parser(
        "show", help="Print seeded compliance data (frameworks, themes, features) as a tree"
    )
    show_parser.add_argument("--database-url", required=True)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        from verity.db.migrate import apply_schema
        asyncio.run(apply_schema(args.database_url, drop_existing=args.drop_existing))

    elif args.command == "serve":
        import uvicorn
        from verity.api.app import create_verity_api
        from verity.client.inprocess import Verity

        verity = Verity(database_url=args.database_url)
        app = create_verity_api(verity)
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "web":
        import uvicorn
        from verity.api.app import create_verity_api
        from verity.web.app import create_verity_web
        from verity.client.inprocess import Verity
        from fastapi import FastAPI

        verity = Verity(database_url=args.database_url)
        app = FastAPI(title="Verity")
        app.mount("/api", create_verity_api(verity))
        app.mount("/", create_verity_web(verity))
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "setup":
        if args.target == "docker":
            from verity.setup.docker import generate_docker_compose
            generate_docker_compose(args.output)
        elif args.target == "k8s":
            from verity.setup.k8s import generate_k8s_manifests
            generate_k8s_manifests(args.output)

    elif args.command == "compliance":
        from verity.setup import seed_compliance

        if args.compliance_action == "seed-static":
            counts = asyncio.run(seed_compliance.seed_static(args.database_url))
            print("Static compliance seed complete:")
            for k, v in counts.items():
                print(f"  {k:<22} {v}")
        elif args.compliance_action == "show":
            asyncio.run(seed_compliance.show(args.database_url))
        else:
            compliance_parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
