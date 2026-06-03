"""CLI for appreview-insight."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from appreview import __version__

app = typer.Typer(
    name="appreview",
    help="AppReview Insight — fetch, analyze, and report on mobile app reviews.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)

# ─── Common option types ────────────────────────────────────────────────────

ConfigPathArg = Annotated[
    Path,
    typer.Option("--config", "-c", help="Path to appreview.yaml config file."),
]
VerboseArg = Annotated[bool, typer.Option("--verbose", "-v", help="Enable DEBUG logging.")]
QuietArg = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress INFO logs.")]
DryRunArg = Annotated[
    bool,
    typer.Option("--dry-run", help="Run pipeline without writing to DB or files."),
]
LogFormatArg = Annotated[
    str,
    typer.Option("--log-format", help="Log format: 'text' or 'json'."),
]

DEFAULT_CONFIG = Path("./appreview.yaml")


def _setup_logging(verbose: bool, quiet: bool, log_format: str) -> None:
    """Configure logging based on CLI flags."""
    from appreview.logging import configure_logging

    if verbose:
        level = "DEBUG"
    elif quiet:
        level = "WARNING"
    else:
        level = "INFO"
    configure_logging(level=level, json_format=(log_format.lower() == "json"))


def _parse_since(since_str: str) -> datetime:
    """Parse --since argument into a datetime.

    Accepts: '7d', '24h', '2026-05-01'

    Args:
        since_str: Since string from CLI.

    Returns:
        UTC-aware datetime.

    Raises:
        typer.BadParameter: If format is unrecognized.
    """
    since_str = since_str.strip()
    now = datetime.now(tz=timezone.utc)

    if since_str.endswith("d"):
        try:
            days = int(since_str[:-1])
            return now - timedelta(days=days)
        except ValueError:
            pass
    elif since_str.endswith("h"):
        try:
            hours = int(since_str[:-1])
            return now - timedelta(hours=hours)
        except ValueError:
            pass
    else:
        try:
            dt = datetime.strptime(since_str, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    raise typer.BadParameter(
        f"Invalid --since value: '{since_str}'. "
        "Use formats like '7d', '24h', or '2026-05-01'."
    )


def _get_engine(db_path: Path) -> object:
    """Create async SQLAlchemy engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


def _get_llm_provider(config: object, env: object) -> object:
    """Create LLM provider from config and env.

    Args:
        config: AppReviewConfig instance.
        env: EnvSettings instance.

    Returns:
        LLM provider instance.
    """
    from appreview.config import AppReviewConfig, EnvSettings
    from appreview.llm import AnthropicProvider, OllamaProvider, OpenAIProvider

    assert isinstance(config, AppReviewConfig)
    assert isinstance(env, EnvSettings)

    provider_name = config.llm.provider
    if provider_name == "openai":
        return OpenAIProvider(
            api_key=env.openai_api_key or "",
            classification_model=config.llm.classification_model,
            suggestion_model=config.llm.suggestion_model,
            temperature=config.llm.temperature,
        )
    elif provider_name == "anthropic":
        return AnthropicProvider(
            api_key=env.anthropic_api_key or "",
            classification_model=config.llm.classification_model,
            suggestion_model=config.llm.suggestion_model,
            temperature=config.llm.temperature,
        )
    elif provider_name == "ollama":
        return OllamaProvider(
            base_url=env.ollama_base_url,
            classification_model=config.llm.classification_model,
            suggestion_model=config.llm.suggestion_model,
            temperature=config.llm.temperature,
        )
    else:
        err_console.print(f"[red]Unknown LLM provider: {provider_name}[/red]")
        raise typer.Exit(1)


# ─── Commands ───────────────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Show version and exit."""
    console.print(f"appreview-insight {__version__}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    ver: Annotated[
        bool, typer.Option("--version", help="Show version and exit.")
    ] = False,
) -> None:
    """AppReview Insight — mobile app review analysis CLI."""
    if ver:
        console.print(f"appreview-insight {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command()
def init(
    config: ConfigPathArg = DEFAULT_CONFIG,
) -> None:
    """Interactively create appreview.yaml and .env.example."""
    _run_init(config)


def _run_init(config_path: Path) -> None:
    """Interactive setup wizard."""
    console.print("[bold green]AppReview Insight — Setup Wizard[/bold green]")
    console.print("")

    if config_path.exists():
        overwrite = typer.confirm(
            f"{config_path} already exists. Overwrite?", default=False
        )
        if not overwrite:
            console.print("Setup cancelled.")
            raise typer.Exit(0)

    apps_config: list[dict[str, object]] = []

    # iOS app
    if typer.confirm("Add an iOS app (App Store)?", default=True):
        name = typer.prompt("  App name", default="My iOS App")
        app_id = typer.prompt("  App ID (numeric, e.g. 1234567890)")
        territories_str = typer.prompt(
            "  Territory codes (comma-separated, e.g. JP,US) or leave empty for all",
            default="",
        )
        territories = (
            [t.strip() for t in territories_str.split(",") if t.strip()]
            if territories_str
            else None
        )
        apps_config.append({
            "name": name,
            "source": "app_store",
            "app_id": app_id,
            **({"territories": territories} if territories else {}),
        })

    # Android app
    if typer.confirm("Add an Android app (Google Play)?", default=True):
        name = typer.prompt("  App name", default="My Android App")
        pkg = typer.prompt("  Package name (e.g. com.example.myapp)")
        apps_config.append({
            "name": name,
            "source": "google_play",
            "package_name": pkg,
        })

    if not apps_config:
        err_console.print(
            "[red]No apps configured. Please add at least one app.[/red]"
        )
        raise typer.Exit(1)

    # LLM provider
    provider = typer.prompt(
        "LLM provider",
        default="openai",
        show_choices=True,
        type=typer.Choice(["openai", "anthropic", "ollama"]),
    )

    # Output directory
    output_dir = typer.prompt("Output directory for reports", default="./reports")

    # Build YAML content
    import yaml

    yaml_content = {
        "apps": apps_config,
        "llm": {
            "provider": provider,
            "classification_model": "gpt-4o-mini" if provider == "openai" else
            "claude-3-5-haiku-20241022" if provider == "anthropic" else "llama3",
            "suggestion_model": "gpt-4o" if provider == "openai" else
            "claude-3-5-sonnet-20241022" if provider == "anthropic" else "llama3",
            "max_cost_usd_per_run": 5.00,
            "batch_size": 20,
            "temperature": 0.2,
        },
        "analysis": {
            "categories": [
                "performance", "ui_ux", "feature_request", "bug_crash",
                "billing", "auth", "notification", "other",
            ],
            "min_reviews_for_cluster": 3,
            "pii_masking": True,
        },
        "output": {
            "formats": ["markdown", "json"],
            "output_dir": output_dir,
            "filename_template": "{date}-{app_name}-report",
        },
        "storage": {
            "database_path": "./appreview.db",
            "anonymize_reviewers": False,
        },
        "fetch": {
            "since_days": 7,
            "request_delay_ms": 200,
        },
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w") as f:
        yaml.dump(yaml_content, f, allow_unicode=True, default_flow_style=False)

    console.print(f"\n[green]✓[/green] Created {config_path}")

    # Create .env if not exists
    env_path = Path(".env")
    if not env_path.exists():
        from pathlib import Path as P
        P(".env.example").exists() and P(".env.example").read_text()
        env_path.write_text(
            "# AppReview Insight — environment variables\n"
            "# Copy from .env.example and fill in your credentials\n\n"
            "APP_STORE_ISSUER_ID=\n"
            "APP_STORE_KEY_ID=\n"
            "APP_STORE_PRIVATE_KEY_PATH=./secrets/AuthKey_XXX.p8\n"
            "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=./secrets/service-account.json\n"
            "OPENAI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
            "OLLAMA_BASE_URL=http://localhost:11434\n"
        )
        console.print(f"[green]✓[/green] Created {env_path}")

    console.print("")
    console.print("[bold]Next steps:[/bold]")
    console.print("  1. Fill in credentials in .env")
    console.print("  2. Run: [cyan]appreview doctor[/cyan]  (verify setup)")
    console.print("  3. Run: [cyan]appreview run[/cyan]  (fetch + analyze + report)")


@app.command()
def doctor(
    config: ConfigPathArg = DEFAULT_CONFIG,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Check authentication and connectivity for all configured sources."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_doctor(config))


async def _run_doctor(config_path: Path) -> None:
    """Run connectivity health checks."""
    from appreview.config import load_config, load_env_settings, validate_provider_credentials
    from appreview.exceptions import ConfigError

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    env = load_env_settings()

    console.print("[bold]AppReview Insight — Doctor[/bold]\n")

    # Check credential completeness
    errors = validate_provider_credentials(config, env)

    table = Table(title="Configuration Check")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    if errors:
        for error in errors:
            table.add_row("Credentials", "[red]✗ FAIL[/red]", error)
    else:
        table.add_row("Credentials", "[green]✓ OK[/green]", "All required env vars set")

    console.print(table)

    if errors:
        console.print(
            "\n[yellow]Fix the above issues before running 'appreview run'.[/yellow]"
        )
        console.print(
            "See docs/setup-app-store.md and docs/setup-google-play.md for setup instructions."
        )
        raise typer.Exit(2)

    # Connectivity tests
    console.print("\n[bold]Connectivity Tests[/bold]\n")
    conn_table = Table()
    conn_table.add_column("Source", style="cyan")
    conn_table.add_column("App")
    conn_table.add_column("Status")
    conn_table.add_column("Details")

    all_healthy = True

    for app_cfg in config.apps:
        source = _create_source(app_cfg, env, config.fetch.request_delay_ms)
        if source is None:
            continue

        status = await source.health_check()
        icon = "[green]✓ OK[/green]" if status.healthy else "[red]✗ FAIL[/red]"
        details = status.message
        if status.latency_ms:
            details += f" ({status.latency_ms:.0f}ms)"

        conn_table.add_row(app_cfg.source, app_cfg.name, icon, details)

        if not status.healthy:
            all_healthy = False

    console.print(conn_table)

    if not all_healthy:
        raise typer.Exit(2)

    console.print("\n[green]All checks passed![/green]")


def _create_source(app_cfg: object, env: object, delay_ms: int) -> object:
    """Create a data source instance for an app config."""
    from appreview.config import AppConfig, EnvSettings
    from appreview.sources import AppStoreSource, GooglePlaySource

    assert isinstance(app_cfg, AppConfig)
    assert isinstance(env, EnvSettings)

    if app_cfg.source == "app_store":
        if not all([env.app_store_issuer_id, env.app_store_key_id, env.app_store_private_key_path]):
            return None
        return AppStoreSource(
            app_id=app_cfg.app_id or "",
            issuer_id=env.app_store_issuer_id or "",
            key_id=env.app_store_key_id or "",
            private_key_path=env.app_store_private_key_path,  # type: ignore[arg-type]
            territories=app_cfg.territories,
            request_delay_ms=delay_ms,
        )
    elif app_cfg.source == "google_play":
        if not env.google_play_service_account_json:
            return None
        return GooglePlaySource(
            package_name=app_cfg.package_name or "",
            service_account_json_path=env.google_play_service_account_json,
            request_delay_ms=delay_ms,
        )
    return None


@app.command()
def fetch(
    config: ConfigPathArg = DEFAULT_CONFIG,
    app_name: Annotated[
        Optional[str], typer.Option("--app", help="Name of app to fetch (default: all).")
    ] = None,
    since: Annotated[
        Optional[str], typer.Option("--since", help="Fetch reviews since (e.g. '7d', '24h', '2026-05-01').")
    ] = None,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    dry_run: DryRunArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Fetch reviews from stores and save to database."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_fetch(config, app_name, since, dry_run))


async def _run_fetch(
    config_path: Path,
    app_name: str | None,
    since_str: str | None,
    dry_run: bool,
) -> None:
    """Fetch reviews from stores."""
    from appreview.config import load_config, load_env_settings, validate_provider_credentials
    from appreview.exceptions import AppReviewError, ConfigError
    from appreview.logging import get_logger
    from appreview.storage.migrations import run_migrations
    from appreview.storage.repository import ReviewRepository

    log = get_logger(__name__)

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    env = load_env_settings()
    since = _parse_since(since_str) if since_str else (
        datetime.now(tz=timezone.utc) - timedelta(days=config.fetch.since_days)
    )

    # Select apps to fetch
    apps_to_fetch = [
        a for a in config.apps
        if app_name is None or a.name == app_name
    ]
    if not apps_to_fetch:
        err_console.print(f"[red]No app found with name: {app_name}[/red]")
        raise typer.Exit(1)

    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]

    # Always run migrations (idempotent — safe even in dry-run for reads)
    if not dry_run:
        await run_migrations(engine)  # type: ignore[arg-type]

    from sqlalchemy.ext.asyncio import AsyncSession

    total_new = 0

    for app_cfg in apps_to_fetch:
        source = _create_source(app_cfg, env, config.fetch.request_delay_ms)
        if source is None:
            err_console.print(
                f"[yellow]Skipping {app_cfg.name}: missing credentials.[/yellow]"
            )
            continue

        console.print(f"Fetching reviews for [cyan]{app_cfg.name}[/cyan]...")

        reviews_to_save: list[dict] = []  # type: ignore[type-arg]

        try:
            review_iter = await source.fetch_reviews(since=since)
            async for review in review_iter:
                # Anonymize reviewer nickname if configured
                if config.storage.anonymize_reviewers and review.reviewer_nickname:
                    from appreview.analysis.pii import mask_reviewer_nickname
                    review = review.model_copy(
                        update={"reviewer_nickname": mask_reviewer_nickname(review.reviewer_nickname)}
                    )

                review_dict = review.model_dump()
                review_dict["source"] = review.source
                reviews_to_save.append(review_dict)

        except AppReviewError as e:
            err_console.print(f"[red]Error fetching {app_cfg.name}:[/red] {e}")
            raise typer.Exit(e.exit_code) from e

        if dry_run:
            console.print(
                f"  [yellow][dry-run][/yellow] Would save {len(reviews_to_save)} reviews"
            )
            total_new += len(reviews_to_save)
            continue

        async with AsyncSession(engine) as session:  # type: ignore[arg-type]
            async with session.begin():
                repo = ReviewRepository(session)
                new_count = await repo.upsert_reviews(reviews_to_save)
                total_new += new_count

        console.print(
            f"  [green]✓[/green] Saved {new_count} new reviews "
            f"({len(reviews_to_save) - new_count} duplicates skipped)"
        )

    console.print(f"\n[bold]Total new reviews:[/bold] {total_new}")

    await engine.dispose()  # type: ignore[attr-defined]


@app.command()
def analyze(
    config: ConfigPathArg = DEFAULT_CONFIG,
    run_id: Annotated[
        Optional[str], typer.Option("--run-id", help="Analyze within a specific run ID.")
    ] = None,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    dry_run: DryRunArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Classify and cluster existing reviews in the database."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_analyze(config, run_id, dry_run))


async def _run_analyze(
    config_path: Path,
    run_id: str | None,
    dry_run: bool,
) -> None:
    """Run analysis pipeline on stored reviews."""
    from appreview.analysis.classifier import ReviewClassifier
    from appreview.analysis.clusterer import ReviewClusterer
    from appreview.config import load_config, load_env_settings
    from appreview.exceptions import ConfigError
    from appreview.storage.migrations import run_migrations
    from appreview.storage.repository import (
        ClassificationRepository,
        ClusterRepository,
        ReviewRepository,
        RunRepository,
    )

    from sqlalchemy.ext.asyncio import AsyncSession

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    env = load_env_settings()
    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]

    if not dry_run:
        await run_migrations(engine)  # type: ignore[arg-type]

    llm_provider = _get_llm_provider(config, env)

    classifier = ReviewClassifier(
        provider=llm_provider,  # type: ignore[arg-type]
        categories=config.analysis.categories,
        batch_size=config.llm.batch_size,
        pii_masking=config.analysis.pii_masking,
    )

    clusterer = ReviewClusterer(
        provider=llm_provider,  # type: ignore[arg-type]
        min_reviews_for_cluster=config.analysis.min_reviews_for_cluster,
    )

    total_cost = Decimal("0")

    for app_cfg in config.apps:
        console.print(f"Analyzing reviews for [cyan]{app_cfg.name}[/cyan]...")

        app_identifier = app_cfg.app_id or app_cfg.package_name or ""

        async with AsyncSession(engine) as session:  # type: ignore[arg-type]
            async with session.begin():
                review_repo = ReviewRepository(session)
                clf_repo = ClassificationRepository(session)
                cluster_repo = ClusterRepository(session)
                run_repo = RunRepository(session)

                # Get or create run
                if run_id:
                    run = await run_repo.get_run(run_id)
                    if run is None:
                        err_console.print(f"[red]Run not found: {run_id}[/red]")
                        raise typer.Exit(1)
                else:
                    if not dry_run:
                        run = await run_repo.create_run(app_name=app_cfg.name)
                    else:
                        # Mock run for dry-run
                        import uuid
                        class MockRun:
                            id = str(uuid.uuid4())
                        run = MockRun()  # type: ignore[assignment]

                # Get unclassified reviews
                reviews = list(await review_repo.get_unclassified_reviews(
                    source=app_cfg.source,
                    app_identifier=app_identifier,
                ))

                if not reviews:
                    console.print("  No unclassified reviews found.")
                    continue

                console.print(f"  Found {len(reviews)} unclassified reviews")

                # Convert ORM to domain models
                from appreview.sources.base import NormalizedReview
                domain_reviews = [
                    NormalizedReview(
                        id=r.id,
                        source=r.source,  # type: ignore[arg-type]
                        app_identifier=r.app_identifier,
                        rating=r.rating,
                        title=r.title,
                        body=r.body,
                        locale=r.locale,
                        detected_language=r.detected_language,
                        created_at=r.created_at,
                        updated_at=r.updated_at,
                        app_version=r.app_version,
                        territory=r.territory,
                        raw_payload=r.raw_payload,
                        fetched_at=r.fetched_at,
                    )
                    for r in reviews
                ]

                # Classify
                if not dry_run:
                    clf_dicts, clf_usage = await classifier.classify_reviews(domain_reviews)
                    await clf_repo.save_classifications(clf_dicts)
                    total_cost += clf_usage.cost_usd
                    console.print(
                        f"  [green]✓[/green] Classified {len(clf_dicts)} classifications"
                    )

                    # Get all classifications for clustering
                    from sqlalchemy import select
                    from appreview.storage.models import ClassificationOrm
                    clf_result = await session.execute(
                        select(ClassificationOrm).where(
                            ClassificationOrm.review_source == app_cfg.source
                        )
                    )
                    all_clfs = list(clf_result.scalars().all())

                    # Cluster negative reviews
                    cluster_dicts, cluster_usage = await clusterer.cluster_all(
                        reviews, all_clfs, run.id
                    )
                    if cluster_dicts:
                        await cluster_repo.save_clusters(cluster_dicts)
                    total_cost += cluster_usage.cost_usd

                    console.print(
                        f"  [green]✓[/green] Generated {len(cluster_dicts)} clusters"
                    )

                    # Update run record
                    await run_repo.update_run(
                        run.id,
                        reviews_classified=len(domain_reviews),
                        llm_cost_usd=float(total_cost),
                        status="success",
                        finished_at=datetime.now(tz=timezone.utc),
                    )
                else:
                    console.print(
                        f"  [yellow][dry-run][/yellow] Would classify {len(domain_reviews)} reviews"
                    )

    console.print(f"\n[bold]Total LLM cost:[/bold] ${float(total_cost):.4f}")
    await engine.dispose()  # type: ignore[attr-defined]


@app.command("run")
def run_pipeline(
    config: ConfigPathArg = DEFAULT_CONFIG,
    app_name: Annotated[
        Optional[str], typer.Option("--app", help="Name of app to process (default: all).")
    ] = None,
    since: Annotated[
        Optional[str], typer.Option("--since", help="Fetch reviews since (e.g. '7d', '24h', '2026-05-01').")
    ] = None,
    yes: Annotated[
        bool, typer.Option("-y", "--yes", help="Auto-approve cost confirmation prompt.")
    ] = False,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    dry_run: DryRunArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Fetch + analyze + generate report (full pipeline)."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_full_pipeline(config, app_name, since, yes, dry_run))


async def _run_full_pipeline(
    config_path: Path,
    app_name: str | None,
    since_str: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Run the full pipeline: fetch → analyze → report."""
    from appreview.analysis.classifier import ReviewClassifier
    from appreview.analysis.clusterer import ReviewClusterer
    from appreview.config import load_config, load_env_settings, validate_provider_credentials
    from appreview.exceptions import AppReviewError, ConfigError, CostLimitExceededError
    from appreview.llm.cost import estimate_tokens
    from appreview.report.json_output import generate_json_report
    from appreview.report.markdown import generate_markdown_report
    from appreview.sources.base import NormalizedReview
    from appreview.storage.migrations import run_migrations
    from appreview.storage.models import ClassificationOrm
    from appreview.storage.repository import (
        ClassificationRepository,
        ClusterRepository,
        ReviewRepository,
        RunRepository,
    )

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    env = load_env_settings()

    # Check credentials
    cred_errors = validate_provider_credentials(config, env)
    if cred_errors and not dry_run:
        for error in cred_errors:
            err_console.print(f"[red]Missing credential:[/red] {error}")
        raise typer.Exit(2)

    since = _parse_since(since_str) if since_str else (
        datetime.now(tz=timezone.utc) - timedelta(days=config.fetch.since_days)
    )

    apps_to_process = [
        a for a in config.apps
        if app_name is None or a.name == app_name
    ]

    if not apps_to_process:
        err_console.print(f"[red]No app found with name: {app_name}[/red]")
        raise typer.Exit(1)

    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]
    # Always run migrations to ensure tables exist (idempotent)
    await run_migrations(engine)  # type: ignore[arg-type]

    llm_provider = _get_llm_provider(config, env)

    for app_cfg in apps_to_process:
        console.print(f"\n[bold cyan]Processing: {app_cfg.name}[/bold cyan]")
        app_identifier = app_cfg.app_id or app_cfg.package_name or ""

        async with AsyncSession(engine) as session:  # type: ignore[arg-type]
            async with session.begin():
                run_repo = RunRepository(session)
                review_repo = ReviewRepository(session)
                clf_repo = ClassificationRepository(session)
                cluster_repo = ClusterRepository(session)

                # Create run record
                if not dry_run:
                    run = await run_repo.create_run(app_name=app_cfg.name)
                else:
                    import uuid as uuid_mod
                    class MockRun:
                        id = str(uuid_mod.uuid4())
                    run = MockRun()  # type: ignore[assignment]

                run_id = run.id

                # ── Step 1: Fetch ──────────────────────────────────────
                console.print("  [1/3] Fetching reviews...")
                source = _create_source(app_cfg, env, config.fetch.request_delay_ms)

                all_reviews_for_app: list[dict] = []  # type: ignore[type-arg]
                if source is not None:
                    try:
                        review_iter = await source.fetch_reviews(since=since)
                        async for review in review_iter:
                            if config.storage.anonymize_reviewers and review.reviewer_nickname:
                                from appreview.analysis.pii import mask_reviewer_nickname
                                review = review.model_copy(
                                    update={"reviewer_nickname": mask_reviewer_nickname(review.reviewer_nickname)}
                                )
                            all_reviews_for_app.append(review.model_dump())
                    except AppReviewError as e:
                        err_console.print(f"  [red]Fetch error:[/red] {e}")
                        if not dry_run:
                            await run_repo.update_run(
                                run_id,
                                status="failed",
                                error_message=str(e),
                                finished_at=datetime.now(tz=timezone.utc),
                            )
                        raise typer.Exit(e.exit_code) from e

                if not dry_run and all_reviews_for_app:
                    new_count = await review_repo.upsert_reviews(all_reviews_for_app)
                    console.print(f"     ✓ {new_count} new reviews saved")
                    await run_repo.update_run(run_id, reviews_fetched=len(all_reviews_for_app))
                elif dry_run:
                    console.print(
                        f"     [yellow][dry-run][/yellow] Would save {len(all_reviews_for_app)} reviews"
                    )

                # ── Step 2: Classify ───────────────────────────────────
                console.print("  [2/3] Classifying reviews...")

                db_reviews = list(await review_repo.get_reviews_for_run(
                    source=app_cfg.source,
                    app_identifier=app_identifier,
                    since=since,
                ))

                if not db_reviews:
                    console.print("     No reviews to classify.")
                    if not dry_run:
                        await run_repo.update_run(
                            run_id,
                            status="success",
                            finished_at=datetime.now(tz=timezone.utc),
                        )
                    continue

                domain_reviews = [
                    NormalizedReview(
                        id=r.id,
                        source=r.source,  # type: ignore[arg-type]
                        app_identifier=r.app_identifier,
                        rating=r.rating,
                        title=r.title,
                        body=r.body,
                        locale=r.locale,
                        detected_language=r.detected_language,
                        created_at=r.created_at,
                        updated_at=r.updated_at,
                        app_version=r.app_version,
                        territory=r.territory,
                        raw_payload=r.raw_payload,
                        fetched_at=r.fetched_at,
                    )
                    for r in db_reviews
                ]

                # Cost estimate
                total_chars = sum(len(r.body) for r in domain_reviews)
                est_input_tokens = estimate_tokens(" ".join(r.body for r in domain_reviews[:5]) * (len(domain_reviews) // 5 + 1))
                est_output_tokens = len(domain_reviews) * 20
                est_cost = llm_provider.estimate_cost(  # type: ignore[attr-defined]
                    est_input_tokens, est_output_tokens,
                    config.llm.classification_model
                )

                if not dry_run and float(est_cost) > config.llm.max_cost_usd_per_run:
                    if not yes:
                        console.print(
                            f"  [yellow]⚠ Estimated cost ${float(est_cost):.4f} exceeds "
                            f"limit ${config.llm.max_cost_usd_per_run:.2f}[/yellow]"
                        )
                        if not typer.confirm("Continue anyway?"):
                            raise typer.Exit(5)

                classifier = ReviewClassifier(
                    provider=llm_provider,  # type: ignore[arg-type]
                    categories=config.analysis.categories,
                    batch_size=config.llm.batch_size,
                    pii_masking=config.analysis.pii_masking,
                )

                total_cost = Decimal("0")

                if not dry_run:
                    clf_dicts, clf_usage = await classifier.classify_reviews(domain_reviews)
                    await clf_repo.save_classifications(clf_dicts)
                    total_cost += clf_usage.cost_usd
                    console.print(f"     ✓ Classified {len(domain_reviews)} reviews (${float(clf_usage.cost_usd):.4f})")
                else:
                    console.print(
                        f"     [yellow][dry-run][/yellow] Would classify {len(domain_reviews)} reviews"
                    )

                # ── Step 3: Cluster & Report ───────────────────────────
                console.print("  [3/3] Clustering & generating report...")

                if not dry_run:
                    clf_result = await session.execute(
                        select(ClassificationOrm).where(
                            ClassificationOrm.review_source == app_cfg.source
                        )
                    )
                    all_clfs = list(clf_result.scalars().all())

                    clusterer = ReviewClusterer(
                        provider=llm_provider,  # type: ignore[arg-type]
                        min_reviews_for_cluster=config.analysis.min_reviews_for_cluster,
                    )
                    cluster_dicts, cluster_usage = await clusterer.cluster_all(
                        db_reviews, all_clfs, run_id
                    )
                    if cluster_dicts:
                        await cluster_repo.save_clusters(cluster_dicts)
                    total_cost += cluster_usage.cost_usd

                    # Get cluster ORM objects for report
                    cluster_orm_list = list(await cluster_repo.get_clusters_for_run(run_id))

                    # Generate report
                    output_dir = Path(config.output.output_dir)
                    if not dry_run:
                        output_dir.mkdir(parents=True, exist_ok=True)

                    safe_name = app_cfg.name.lower().replace(" ", "_")
                    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
                    base_name = (
                        config.output.filename_template
                        .replace("{date}", date_str)
                        .replace("{app_name}", safe_name)
                    )

                    for fmt in config.output.formats:
                        if fmt == "markdown":
                            md = generate_markdown_report(
                                run, app_cfg, db_reviews, all_clfs, cluster_orm_list
                            )
                            out_path = output_dir / f"{base_name}.md"
                            out_path.write_text(md, encoding="utf-8")
                            console.print(f"     ✓ Report: {out_path}")

                        elif fmt == "json":
                            json_str = generate_json_report(
                                run, app_cfg, db_reviews, all_clfs, cluster_orm_list
                            )
                            out_path = output_dir / f"{base_name}.json"
                            out_path.write_text(json_str, encoding="utf-8")
                            console.print(f"     ✓ Report: {out_path}")

                    # Update run
                    await run_repo.update_run(
                        run_id,
                        status="success",
                        reviews_classified=len(domain_reviews),
                        llm_cost_usd=float(total_cost),
                        finished_at=datetime.now(tz=timezone.utc),
                    )
                else:
                    console.print(
                        "     [yellow][dry-run][/yellow] Would generate reports"
                    )

        console.print(f"\n  [green]✓[/green] Run ID: {run_id}")
        if not dry_run:
            console.print(f"  [green]✓[/green] Total cost: ${float(total_cost):.4f}")

    await engine.dispose()  # type: ignore[attr-defined]


@app.command("report")
def generate_report(
    config: ConfigPathArg = DEFAULT_CONFIG,
    run_id: Annotated[str, typer.Option("--run-id", help="Run ID to generate report for.")] = "",
    fmt: Annotated[
        str, typer.Option("--format", help="Output format: 'md' or 'json'.")
    ] = "md",
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Regenerate report for a previous run."""
    _setup_logging(verbose, quiet, log_format)
    if not run_id:
        err_console.print("[red]--run-id is required[/red]")
        raise typer.Exit(1)
    asyncio.run(_run_report(config, run_id, fmt))


async def _run_report(config_path: Path, run_id: str, fmt: str) -> None:
    """Regenerate report from existing run data."""
    from appreview.config import load_config
    from appreview.exceptions import ConfigError
    from appreview.report.json_output import generate_json_report
    from appreview.report.markdown import generate_markdown_report
    from appreview.storage.migrations import run_migrations
    from appreview.storage.repository import ClusterRepository, RunRepository

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from appreview.storage.models import ClassificationOrm, ReviewOrm

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]
    await run_migrations(engine)  # type: ignore[arg-type]

    async with AsyncSession(engine) as session:  # type: ignore[arg-type]
        run_repo = RunRepository(session)
        cluster_repo = ClusterRepository(session)

        run = await run_repo.get_run(run_id)
        if run is None:
            err_console.print(f"[red]Run not found: {run_id}[/red]")
            raise typer.Exit(1)

        # Get associated app config
        app_cfg = next(
            (a for a in config.apps if a.name == run.app_name),
            config.apps[0] if config.apps else None,
        )
        if app_cfg is None:
            err_console.print("[red]No app config found for this run.[/red]")
            raise typer.Exit(1)

        app_identifier = app_cfg.app_id or app_cfg.package_name or ""

        # Load reviews and classifications
        reviews_result = await session.execute(
            select(ReviewOrm).where(
                ReviewOrm.source == app_cfg.source,
                ReviewOrm.app_identifier == app_identifier,
            )
        )
        db_reviews = list(reviews_result.scalars().all())

        clf_result = await session.execute(
            select(ClassificationOrm).where(
                ClassificationOrm.review_source == app_cfg.source
            )
        )
        all_clfs = list(clf_result.scalars().all())

        clusters = list(await cluster_repo.get_clusters_for_run(run_id))

        output_dir = Path(config.output.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = app_cfg.name.lower().replace(" ", "_")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        base_name = (
            config.output.filename_template
            .replace("{date}", date_str)
            .replace("{app_name}", safe_name)
        )

        if fmt in ("md", "markdown"):
            md = generate_markdown_report(run, app_cfg, db_reviews, all_clfs, clusters)
            out_path = output_dir / f"{base_name}.md"
            out_path.write_text(md, encoding="utf-8")
            console.print(f"[green]✓[/green] Report written to {out_path}")

        elif fmt == "json":
            json_str = generate_json_report(run, app_cfg, db_reviews, all_clfs, clusters)
            out_path = output_dir / f"{base_name}.json"
            out_path.write_text(json_str, encoding="utf-8")
            console.print(f"[green]✓[/green] Report written to {out_path}")

        else:
            err_console.print(f"[red]Unknown format: {fmt}. Use 'md' or 'json'.[/red]")
            raise typer.Exit(1)

    await engine.dispose()  # type: ignore[attr-defined]


@app.command("cost-estimate")
def cost_estimate(
    config: ConfigPathArg = DEFAULT_CONFIG,
    since: Annotated[
        Optional[str], typer.Option("--since", help="Estimate cost for reviews since.")
    ] = None,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """Estimate LLM cost for the next run."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_cost_estimate(config, since))


async def _run_cost_estimate(config_path: Path, since_str: str | None) -> None:
    """Estimate cost based on unclassified reviews."""
    from appreview.config import load_config
    from appreview.exceptions import ConfigError
    from appreview.llm.cost import estimate_tokens
    from appreview.storage.migrations import run_migrations
    from appreview.storage.repository import ReviewRepository

    from sqlalchemy.ext.asyncio import AsyncSession

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    since = _parse_since(since_str) if since_str else (
        datetime.now(tz=timezone.utc) - timedelta(days=config.fetch.since_days)
    )

    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]
    await run_migrations(engine)  # type: ignore[arg-type]

    llm_provider = _get_llm_provider(config, env := load_env_settings())  # type: ignore[arg-type]

    total_cost = Decimal("0")
    total_reviews = 0

    console.print("[bold]Cost Estimate[/bold]\n")

    async with AsyncSession(engine) as session:  # type: ignore[arg-type]
        for app_cfg in config.apps:
            app_identifier = app_cfg.app_id or app_cfg.package_name or ""
            repo = ReviewRepository(session)
            reviews = list(await repo.get_unclassified_reviews(
                source=app_cfg.source,
                app_identifier=app_identifier,
            ))

            if not reviews:
                console.print(f"  {app_cfg.name}: 0 unclassified reviews")
                continue

            total_chars = sum(len(r.body) for r in reviews)
            est_input = estimate_tokens(" " * total_chars)
            est_output = len(reviews) * 20

            cost = llm_provider.estimate_cost(  # type: ignore[attr-defined]
                est_input, est_output, config.llm.classification_model
            )

            console.print(
                f"  {app_cfg.name}: {len(reviews)} reviews → "
                f"~{est_input} input tokens → ${float(cost):.4f}"
            )

            total_cost += cost
            total_reviews += len(reviews)

    console.print(f"\n[bold]Total:[/bold] {total_reviews} reviews, estimated cost: [cyan]${float(total_cost):.4f}[/cyan]")

    if float(total_cost) > config.llm.max_cost_usd_per_run:
        console.print(
            f"[yellow]⚠ Exceeds configured limit: ${config.llm.max_cost_usd_per_run:.2f}[/yellow]"
        )

    await engine.dispose()  # type: ignore[attr-defined]


@app.command("list-runs")
def list_runs(
    config: ConfigPathArg = DEFAULT_CONFIG,
    limit: Annotated[int, typer.Option("--limit", help="Maximum runs to show.")] = 20,
    verbose: VerboseArg = False,
    quiet: QuietArg = False,
    log_format: LogFormatArg = "text",
) -> None:
    """List past analysis runs."""
    _setup_logging(verbose, quiet, log_format)
    asyncio.run(_run_list_runs(config, limit))


async def _run_list_runs(config_path: Path, limit: int) -> None:
    """List run history from database."""
    from appreview.config import load_config
    from appreview.exceptions import ConfigError
    from appreview.storage.migrations import run_migrations
    from appreview.storage.repository import RunRepository

    from sqlalchemy.ext.asyncio import AsyncSession

    try:
        config = load_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    engine = _get_engine(config.storage.database_path)  # type: ignore[arg-type]
    await run_migrations(engine)  # type: ignore[arg-type]

    async with AsyncSession(engine) as session:  # type: ignore[arg-type]
        repo = RunRepository(session)
        runs = list(await repo.list_runs(limit=limit))

    if not runs:
        console.print("No runs found. Run 'appreview run' to start.")
        await engine.dispose()  # type: ignore[attr-defined]
        return

    table = Table(title="Recent Runs")
    table.add_column("Run ID", style="dim", max_width=12)
    table.add_column("App")
    table.add_column("Started")
    table.add_column("Status")
    table.add_column("Reviews")
    table.add_column("Cost")

    for run in runs:
        status_display = {
            "success": "[green]✓ success[/green]",
            "failed": "[red]✗ failed[/red]",
            "running": "[yellow]⟳ running[/yellow]",
        }.get(run.status, run.status)

        started = _format_dt_short(run.started_at)

        table.add_row(
            run.id[:8] + "...",
            run.app_name or "N/A",
            started,
            status_display,
            str(run.reviews_classified),
            f"${run.llm_cost_usd:.4f}",
        )

    console.print(table)
    await engine.dispose()  # type: ignore[attr-defined]


def _format_dt_short(dt: datetime | None) -> str:
    """Format datetime for table display."""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")
