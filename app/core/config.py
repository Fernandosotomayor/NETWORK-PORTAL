"""Application configuration using pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000

    # Base directory of the workspace
    BASE_DIR: Path = Path(__file__).resolve().parents[2]

    # Directories that can be relative or absolute
    DATA_DIR: Path = Path("normalized_json")
    STATIC_DIR: Path = Path("app/static")
    TEMPLATES_DIR: Path = Path("app/templates")
    BACKUPS_GIT_DIR: Path = Path("backups")
    STATE_FILE: Path = Path("data/topology_state.json")
    OXIDIZED_ARCHIVE_DIR: Path = Path(r"C:\Users\fernando.sotomayor\SCHIAPPACASSE INVESTMENT S.A\Gerencia TI - Infraestructura - Documentos\Infraestructura\Backup\switches 2026 - oxidized\oxidized-archive")
    OXIDIZED_REPO_URL: str = "git@github.com:STLi-SPA/INFRA-BACKUPS.git"
    OXIDIZED_URL: str = "http://10.40.20.70:8888"

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> Settings:
        """Resolve any relative paths against the project BASE_DIR."""
        if not self.DATA_DIR.is_absolute():
            self.DATA_DIR = (self.BASE_DIR / self.DATA_DIR).resolve()
        if not self.STATIC_DIR.is_absolute():
            self.STATIC_DIR = (self.BASE_DIR / self.STATIC_DIR).resolve()
        if not self.TEMPLATES_DIR.is_absolute():
            self.TEMPLATES_DIR = (self.BASE_DIR / self.TEMPLATES_DIR).resolve()
        if not self.BACKUPS_GIT_DIR.is_absolute():
            self.BACKUPS_GIT_DIR = (self.BASE_DIR / self.BACKUPS_GIT_DIR).resolve()
        if not self.STATE_FILE.is_absolute():
            self.STATE_FILE = (self.BASE_DIR / self.STATE_FILE).resolve()
        if not self.OXIDIZED_ARCHIVE_DIR.is_absolute():
            self.OXIDIZED_ARCHIVE_DIR = (self.BASE_DIR / self.OXIDIZED_ARCHIVE_DIR).resolve()
        return self


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
