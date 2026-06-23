"""Command line entry point and public parse_file API."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from .parser_factory import ParserFactory

LOGGER = logging.getLogger(__name__)


def parse_file(path: str | Path) -> dict[str, Any]:
    """Parse one backup file and return the required normalized dictionary."""
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8", errors="replace")
    parser = ParserFactory.from_text(text)
    switch = parser.parse(text, source_path)
    return switch.to_dict()


def parse_file_with_metadata(path: str | Path) -> dict[str, Any]:
    """Parse one backup file and include metadata, warnings, and parser family."""
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8", errors="replace")
    parser = ParserFactory.from_text(text)
    switch = parser.parse(text, source_path)
    return switch.to_dict(include_metadata=True)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Parse Planet switch backup configs.")
    arg_parser.add_argument("paths", nargs="+", help="Backup .cfg file or directory paths")
    arg_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("normalized_json"),
        help="Directory where normalized JSON files will be written",
    )
    arg_parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = arg_parser.parse_args()

    configure_logging(args.verbose)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.glob("*.cfg")))
        else:
            files.append(path)

    parsed = 0
    errors = 0
    warnings = 0

    for cfg_path in files:
        try:
            data = parse_file_with_metadata(cfg_path)
            output_path = args.output_dir / f"{cfg_path.stem}.json"
            output_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            metadata = data.get("metadata") or {}
            file_warnings = len(metadata.get("warnings") or [])
            file_errors = len(metadata.get("errors") or [])
            warnings += file_warnings
            errors += file_errors
            parsed += 1
            LOGGER.info(
                "parsed %s -> %s (%s warnings, %s errors)",
                cfg_path.name,
                output_path,
                file_warnings,
                file_errors,
            )
        except Exception:
            errors += 1
            LOGGER.exception("failed parsing %s", cfg_path)

    print(json.dumps({"parsed": parsed, "warnings": warnings, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
