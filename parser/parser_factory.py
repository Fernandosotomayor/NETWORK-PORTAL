"""Factory for selecting the proper Planet backup parser."""

from __future__ import annotations

from pathlib import Path

from .base_parser import BaseParser
from .planet_cisco_like_parser import PlanetCiscoLikeParser
from .planet_system_config_parser import PlanetSystemConfigParser


class UnsupportedBackupFormatError(ValueError):
    """Raised when a config file does not match known Planet formats."""


class ParserFactory:
    """Detect parser family from backup content."""

    @staticmethod
    def from_text(text: str) -> BaseParser:
        if "SYSTEM CONFIG FILE ::= BEGIN" in text or "! System Description:" in text:
            return PlanetSystemConfigParser()
        if "show running-config" in text and "hostname " in text:
            return PlanetCiscoLikeParser()
        raise UnsupportedBackupFormatError("unsupported Planet backup format")

    @classmethod
    def from_file(cls, path: Path) -> BaseParser:
        return cls.from_text(path.read_text(encoding="utf-8", errors="replace"))
