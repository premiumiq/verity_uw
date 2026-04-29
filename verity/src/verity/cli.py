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

    seed_data_parser = compliance_sub.add_parser(
        "seed-data",
        help="Seed canonical requirements, provisions, bridges, and coverage from compliance_seed_data.yaml",
    )
    seed_data_parser.add_argument("--database-url", required=True)

    seed_reports_parser = compliance_sub.add_parser(
        "seed-reports",
        help="Seed mart_field rows + requirement_evidence_field bridges + report definitions from compliance_seed_reports.yaml",
    )
    seed_reports_parser.add_argument("--database-url", required=True)

    show_parser = compliance_sub.add_parser(
        "show", help="Print seeded compliance data (frameworks, themes, features, canonicals, provisions) as a tree"
    )
    show_parser.add_argument("--database-url", required=True)

    reembed_parser = compliance_sub.add_parser(
        "reembed",
        help="Generate vectors for compliance rows. Staleness-aware by default; use --force to re-embed everything.",
    )
    reembed_parser.add_argument("--database-url", required=True)
    reembed_parser.add_argument(
        "--force", action="store_true",
        help="Re-embed every row (default: only rows missing or stale embeddings).",
    )

    sim_parser = compliance_sub.add_parser(
        "similarity-search",
        help="Embed a query string and return the top-k closest rows from one of the embedded tables.",
    )
    sim_parser.add_argument("--database-url", required=True)
    sim_parser.add_argument("query", help="Natural-language query text to embed and match.")
    sim_parser.add_argument(
        "--top-k", type=int, default=5, help="Number of matches to return (default: 5).",
    )
    sim_parser.add_argument(
        "--table",
        choices=["canonical_requirement", "regulatory_provision", "feature"],
        default="canonical_requirement",
        help="Which embedded table to search (default: canonical_requirement).",
    )

    export_parser = compliance_sub.add_parser(
        "export",
        help="Bundle the L2 mart + L3 metamodel + L4/L5 artifacts into a directory for customer-warehouse ingest.",
    )
    export_parser.add_argument("--database-url", required=True)
    export_parser.add_argument("--out", required=True, help="Output directory.")
    export_parser.add_argument("--since", default=None, help="ISO timestamp; defaults to 1970-01-01.")
    export_parser.add_argument("--until", default=None, help="ISO timestamp; defaults to now.")

    publish_parser = compliance_sub.add_parser(
        "publish",
        help="Publish the L2 mart to MinIO in Iceberg-style continuous layout (bucket/compliance/<view>/<fingerprint>/<batch_ts>/*.parquet).",
    )
    publish_parser.add_argument("--database-url", required=True)
    publish_parser.add_argument("--bucket", default=None, help="Override bucket name (default: $VERITY_DATA_HUB_BUCKET or verity-data-hub).")
    publish_parser.add_argument("--since", default=None)
    publish_parser.add_argument("--until", default=None)

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
        elif args.compliance_action == "seed-data":
            counts = asyncio.run(seed_compliance.seed_data(args.database_url))
            print("Compliance data seed complete:")
            for k, v in counts.items():
                print(f"  {k:<28} {v}")
        elif args.compliance_action == "seed-reports":
            counts = asyncio.run(seed_compliance.seed_reports(args.database_url))
            print("Reports seed complete:")
            for k, v in counts.items():
                print(f"  {k:<32} {v}")
        elif args.compliance_action == "show":
            asyncio.run(seed_compliance.show(args.database_url))
        elif args.compliance_action == "reembed":
            counts = asyncio.run(
                seed_compliance.reembed(args.database_url, force=args.force)
            )
            print("Embedding pass complete:")
            for k, v in counts.items():
                print(f"  {k:<46} {v} row(s)")
        elif args.compliance_action == "similarity-search":
            asyncio.run(
                seed_compliance.similarity_search(
                    args.database_url,
                    args.query,
                    top_k=args.top_k,
                    table=args.table,
                )
            )
        elif args.compliance_action == "export":
            from pathlib import Path
            from verity.setup.export_compliance import export_bundle
            manifest = asyncio.run(
                export_bundle(
                    args.database_url,
                    Path(args.out),
                    since=args.since,
                    until=args.until,
                )
            )
            total = sum(v["row_count"] for v in manifest["views"])
            print()
            print(f"Done. {total} total row(s) across {len(manifest['views'])} view(s).")
            print(f"Manifest: {Path(args.out) / 'manifest.json'}")
        elif args.compliance_action == "publish":
            from verity.setup.publish_compliance import publish_bundle
            kwargs = dict(since=args.since, until=args.until)
            if args.bucket:
                kwargs["bucket"] = args.bucket
            result = asyncio.run(publish_bundle(args.database_url, **kwargs))
            print()
            print(f"Done. batch_ts={result['batch_ts']}")
            print(f"Manifest: s3://{result['bucket']}/{result['manifest_key']}")
        else:
            compliance_parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
