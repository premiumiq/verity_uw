"""Verity CLI entry points.

Usage:
    verity init     — Create database and apply schema
    verity serve    — Run API server
    verity web      — Run web UI (API + admin interface)
    verity setup    — Generate infrastructure configs
    verity export   — Export an entity (with deps) as a YAML bundle
    verity import   — Import a YAML bundle into the registry
    verity diff     — Preview what an import would change in the DB
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

    # ── verity export — write a YAML bundle for one entity (with deps)
    yaml_export_parser = subparsers.add_parser(
        "export",
        help="Export a Verity entity (and its dependencies) as a YAML bundle.",
    )
    yaml_export_parser.add_argument(
        "kind",
        choices=[
            "agent", "task", "prompt", "tool",
            "inference_config", "data_connector",
        ],
        help="Entity type to export.",
    )
    yaml_export_parser.add_argument("name", help="Entity name.")
    yaml_export_parser.add_argument(
        "--version", default=None,
        help=(
            "Specific version_label (e.g. '1.2.0') for agent/task/prompt. "
            "Omit to include every version of the starting entity."
        ),
    )
    yaml_export_parser.add_argument("--database-url", required=True)
    yaml_export_parser.add_argument(
        "--output", "-o", default=None,
        help="File path to write to. Omit to write to stdout.",
    )

    # ── verity import — read a YAML bundle and persist it
    yaml_import_parser = subparsers.add_parser(
        "import",
        help="Import a YAML bundle into the registry. New rows created as draft.",
    )
    yaml_import_parser.add_argument(
        "file", nargs="?", default=None,
        help="YAML file path. Omit to read from stdin.",
    )
    yaml_import_parser.add_argument("--database-url", required=True)

    # ── verity diff — preview what an import would change
    yaml_diff_parser = subparsers.add_parser(
        "diff",
        help="Preview what an import would change in the database (no writes).",
    )
    yaml_diff_parser.add_argument("file", help="YAML file path to compare against the database.")
    yaml_diff_parser.add_argument("--database-url", required=True)

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

    elif args.command == "export":
        sys.exit(asyncio.run(_run_yaml_export(args)))

    elif args.command == "import":
        sys.exit(asyncio.run(_run_yaml_import(args)))

    elif args.command == "diff":
        sys.exit(asyncio.run(_run_yaml_diff(args)))


# ── YAML CLI handlers ────────────────────────────────────────────────────
# These wrap the in-process Verity SDK rather than calling /api/v1/yaml/*
# over HTTP. Power users running the CLI locally don't need a running
# server, and an in-process call is faster and easier to script in CI.


async def _run_yaml_export(args) -> int:
    """Handle ``verity export <kind> <name>``.

    Connects to the database, walks the dependency graph from the
    starting entity, and writes the bundle as YAML text to either a
    file or stdout. Returns a process exit code.
    """
    from pathlib import Path

    from verity.client.inprocess import Verity
    from verity.governance.yaml_io import Exporter, dumps_bundle

    verity = Verity(database_url=args.database_url)
    await verity.connect()
    try:
        exporter = Exporter(verity.registry)
        method = getattr(exporter, f"export_{args.kind}")
        if args.kind in ("agent", "task", "prompt"):
            bundle = await method(args.name, version=args.version)
        else:
            if args.version is not None:
                print(
                    f"--version is not valid for kind '{args.kind}' "
                    "(only agent / task / prompt are versioned).",
                    file=sys.stderr,
                )
                return 2
            bundle = await method(args.name)

        if not bundle.entities:
            print(
                f"No {args.kind} found with name {args.name!r}.",
                file=sys.stderr,
            )
            return 1

        yaml_text = dumps_bundle(bundle)
        if args.output:
            Path(args.output).write_text(yaml_text)
            print(f"Wrote {len(bundle.entities)} entity bundle to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(yaml_text)
        return 0
    finally:
        await verity.close()


async def _run_yaml_import(args) -> int:
    """Handle ``verity import [FILE]``.

    Reads YAML from a file or stdin, runs the importer, prints a
    per-entity summary. Validation failures print structured errors
    and exit non-zero so CI scripts can detect them.
    """
    import yaml as yaml_lib
    from pathlib import Path

    from pydantic import ValidationError

    from verity.client.inprocess import Verity
    from verity.governance.yaml_io import (
        Importer,
        ImportValidationError,
        loads_bundle,
    )

    if args.file:
        try:
            yaml_text = Path(args.file).read_text()
        except OSError as exc:
            print(f"Could not read {args.file}: {exc}", file=sys.stderr)
            return 2
    else:
        yaml_text = sys.stdin.read()

    try:
        bundle = loads_bundle(yaml_text)
    except (yaml_lib.YAMLError, ValueError, ValidationError) as exc:
        print(f"Could not parse YAML bundle: {exc}", file=sys.stderr)
        return 2

    verity = Verity(database_url=args.database_url)
    await verity.connect()
    try:
        importer = Importer(verity.registry)
        try:
            result = await importer.import_bundle(bundle)
        except ImportValidationError as exc:
            print(
                f"Validation failed with {len(exc.errors)} error(s):",
                file=sys.stderr,
            )
            for err in exc.errors:
                print(
                    f"  [{err.code}] {err.path}: {err.message}",
                    file=sys.stderr,
                )
            return 1

        _print_import_summary(result, header_prefix="Imported")
        return 0
    finally:
        await verity.close()


async def _run_yaml_diff(args) -> int:
    """Handle ``verity diff <file>``.

    Parses the YAML bundle, runs the importer's plan-only mode, and
    prints what would change against the current database. No writes.
    """
    from pathlib import Path

    import yaml as yaml_lib
    from pydantic import ValidationError

    from verity.client.inprocess import Verity
    from verity.governance.yaml_io import (
        Importer,
        ImportValidationError,
        loads_bundle,
    )

    try:
        yaml_text = Path(args.file).read_text()
    except OSError as exc:
        print(f"Could not read {args.file}: {exc}", file=sys.stderr)
        return 2

    try:
        bundle = loads_bundle(yaml_text)
    except (yaml_lib.YAMLError, ValueError, ValidationError) as exc:
        print(f"Could not parse YAML bundle: {exc}", file=sys.stderr)
        return 2

    verity = Verity(database_url=args.database_url)
    await verity.connect()
    try:
        importer = Importer(verity.registry)
        try:
            plan = await importer.plan_import(bundle)
        except ImportValidationError as exc:
            print(
                f"Bundle has {len(exc.errors)} validation error(s) "
                "before any diff is meaningful:",
                file=sys.stderr,
            )
            for err in exc.errors:
                print(
                    f"  [{err.code}] {err.path}: {err.message}",
                    file=sys.stderr,
                )
            return 1

        _print_diff_summary(plan, file_path=args.file)
        return 0
    finally:
        await verity.close()


def _print_import_summary(result, *, header_prefix: str) -> None:
    """Pretty-print an ImportResult to stdout.

    ``header_prefix`` lets the same shape serve both the import summary
    ("Imported …") and any future preview command.
    """
    n_create_h = len(result.headers_inserted)
    n_skip_h = len(result.headers_skipped)
    n_create_v = len(result.versions_inserted)
    n_skip_v = len(result.versions_skipped)

    print(f"{header_prefix}: "
          f"{n_create_h + n_create_v} created, "
          f"{n_skip_h + n_skip_v} skipped (already existed)")

    if result.headers_inserted:
        print()
        print("Created:")
        for kind, name in result.headers_inserted:
            print(f"  + {kind:<18} {name}")
        for kind, name, version in result.versions_inserted:
            print(f"  + {kind + ' ' + name:<24} v{version}")

    if result.headers_skipped or result.versions_skipped:
        print()
        print("Skipped (already existed):")
        for kind, name in result.headers_skipped:
            print(f"  = {kind:<18} {name}")
        for kind, name, version in result.versions_skipped:
            print(f"  = {kind + ' ' + name:<24} v{version}")


def _print_diff_summary(plan, *, file_path: str) -> None:
    """Render a ``verity diff`` report from a plan_import result."""
    print(f"Diff: {file_path} vs current database")
    print("=" * (len(file_path) + 24))

    # In a plan, "inserted" means "would be created"; "skipped" means
    # "already exists". Same struct, different framing.
    n_create = len(plan.headers_inserted) + len(plan.versions_inserted)
    n_skip = len(plan.headers_skipped) + len(plan.versions_skipped)

    if n_create == 0:
        print()
        print("No changes — every entity in the bundle already exists.")
    else:
        print()
        print("Would CREATE:")
        for kind, name in plan.headers_inserted:
            print(f"  + {kind:<18} {name}")
        for kind, name, version in plan.versions_inserted:
            print(f"  + {kind + ' ' + name:<24} v{version}")

    if n_skip > 0:
        print()
        print("Would SKIP (already exists):")
        for kind, name in plan.headers_skipped:
            print(f"  = {kind:<18} {name}")
        for kind, name, version in plan.versions_skipped:
            print(f"  = {kind + ' ' + name:<24} v{version}")

    print()
    print(f"Summary: {n_create} would be created, {n_skip} would be skipped.")


if __name__ == "__main__":
    main()
