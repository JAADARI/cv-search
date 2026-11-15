"""Command-line interface: run services, batch-ingest a folder, search, evaluate."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Annotated

import typer

from cvsearch.logging_config import configure_logging
from cvsearch.parsing.loader import SUPPORTED_EXTENSIONS
from cvsearch.services import build_services

app = typer.Typer(help="CV Search command line.", no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command()
def api(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("cvsearch.api.app:app_factory", host=host, port=port, factory=True)


@app.command()
def worker(poll_seconds: float = 2.0) -> None:
    """Run the ingestion worker that drains the queue."""
    from cvsearch.ingestion.worker import run_forever

    services = build_services()
    configure_logging(services.settings.log_level)
    run_forever(services.settings, services.repo, services.pipeline, poll_seconds)


@app.command()
def ingest(
    path: Annotated[Path, typer.Argument(exists=True, help="A CV file or a folder (searched recursively).")],
    wait: Annotated[
        bool, typer.Option(help="Process the queue in this process instead of leaving it to a worker.")
    ] = True,
) -> None:
    """Queue CVs from a path and (by default) process them right away."""
    from cvsearch.ingestion.worker import run_once

    services = build_services()
    configure_logging(services.settings.log_level)
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    queued = 0
    for file in files:
        cv_id, created = services.repo.enqueue(file.name, file.read_bytes())
        queued += created
        typer.echo(f"{'queued   ' if created else 'duplicate'} {file.name} {cv_id}")
    if wait:
        start = time.time()
        while run_once(services.settings, services.repo, services.pipeline):
            pass
        typer.echo(f"processed in {time.time() - start:.0f}s")
    for row in services.repo.list_cvs():
        typer.echo(f"{row['status']:10s} {row['filename']:34s} {row['full_name'] or ''} {row['error'] or ''}")


@app.command()
def search(query: str, top_k: int = 5, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Search profiles with a natural-language query."""
    services = build_services()
    result = services.search.search(query, top_k)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        return
    for criterion in result.interpreted_as.criteria:
        typer.echo(f"  criterion [{criterion.importance}] {criterion.label}")
    if result.no_full_match:
        typer.secho("No profile satisfies every required criterion; closest profiles below.", fg=typer.colors.YELLOW)
    for hit in result.hits:
        typer.echo(
            f"\n{hit.score:.2f}  {hit.full_name} ({hit.current_title}) - {hit.seniority}, {hit.years_of_experience}y"
        )
        typer.echo(f"      {hit.summary}")
        for c in hit.criteria:
            typer.echo(f"      [{c.verdict.value:7s}] {c.criterion} -> {c.evidence}")


@app.command()
def evaluate(
    cases: Annotated[Path, typer.Option(help="JSON file with expected results.")] = Path("data/eval_cases.json"),
    top_k: int = 5,
) -> None:
    """Run the evaluation queries and report recall/precision of the expected profiles."""
    from cvsearch.evaluation.runner import run_evaluation

    services = build_services()
    report = run_evaluation(services.search, json.loads(cases.read_text(encoding="utf-8")), top_k)
    typer.echo(report.render())
    raise typer.Exit(code=0 if report.passed else 1)


if __name__ == "__main__":
    app()
