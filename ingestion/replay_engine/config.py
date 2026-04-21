"""Runtime configuration. Reads from environment variables, with .env support."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReplayConfig(BaseSettings):
    """Replay engine configuration.

    Values are read from the environment; see .env.example at the repo root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kafka_bootstrap_servers: str = Field(default="localhost:19092")
    topic_pitches_raw: str = Field(default="pitches.raw")
    topic_game_state_raw: str = Field(default="game_state.raw")
    topic_corrections_cdc: str = Field(default="corrections.cdc")

    replay_default_speed: float = Field(default=5.0)
    replay_noise_late_arrival_prob: float = Field(default=0.03)
    replay_noise_duplicate_prob: float = Field(default=0.005)
    replay_noise_correction_prob: float = Field(default=0.01)

    log_level: str = Field(default="INFO")


config = ReplayConfig()
