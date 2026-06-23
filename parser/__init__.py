"""Planet switch backup parser package."""

from .models import BackupMetadata, Port, Switch, Vlan

__all__ = ["BackupMetadata", "Port", "Switch", "Vlan", "parse_file"]


def parse_file(path: str):
    from .main import parse_file as _parse_file

    return _parse_file(path)
