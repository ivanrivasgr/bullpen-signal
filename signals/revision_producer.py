"""Batch producer for matchup signal revisions.

Reads silver_matchup_signals from DuckDB, groups by natural key
(game_pk, at_bat_number, pitch_number), orders by event_time, and
applies signals.revision_emitter.detect_revision over consecutive
pairs within each group. Revisions are published to the
features.matchup.v1.revisions Kafka topic via AvroEventPublisher.

The producer is idempotent across runs via a watermark stored in
DuckDB at producer_state.matchup_revision_watermark. The watermark
records the highest natural key triple already processed; subsequent
runs only process signals strictly above it. This means re-running
the producer on the same data emits zero new revisions, which is the
property a batch producer needs for safe re-execution.

This module is the batch incarnation of the revision producer. ADR
0016 schedules a streaming Flink job for 2026-06-20 that will read
from Kafka topics directly and supersede this batch path. Until then,
this is the production path for revisions.

Naming convention for source_event_id: the producer cannot observe
the actual upstream trigger (lineup confirmation, correction event)
because it works against silver_matchup_signals after the fact. The
source_event_id is synthesized as 'batch_producer:{run_id}:{nk}'
where run_id is a UTC timestamp and nk is the natural key triple.
The Phase 3 streaming producer will replace this with the real
upstream event id.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import duckdb
import structlog

from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from signals.matchup_signal import MatchupSignal
from signals.revision_emitter import detect_revision

log = structlog.get_logger(__name__)

DEFAULT_DUCKDB_PATH = Path.home() / ".bullpen" / "dbt.duckdb"
DEFAULT_TOPIC = "features.matchup.v1.revisions"
DEFAULT_BOOTSTRAP = "localhost:19092"
DEFAULT_SCHEMA_REGISTRY = "http://localhost:18081"


@dataclass
class ProducerStats:
    """Counters returned at the end of a producer run."""

    signals_read: int = 0
    groups_processed: int = 0
    revisions_emitted: int = 0
    no_op_pairs: int = 0
    new_watermark: tuple[int, int, int] | None = None


def _ensure_watermark_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the producer_state schema + watermark table if missing.

    The watermark is a single-row table holding the highest natural
    key triple already processed. Multi-row patterns (one row per
    producer instance) are unnecessary for the batch path; one
    producer reads one DuckDB file.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS producer_state")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS producer_state.matchup_revision_watermark (
            game_pk BIGINT NOT NULL,
            at_bat_number INTEGER NOT NULL,
            pitch_number INTEGER NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )


def _load_watermark(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int] | None:
    """Return the current watermark or None if no run has completed yet."""
    row = con.execute(
        "SELECT game_pk, at_bat_number, pitch_number "
        "FROM producer_state.matchup_revision_watermark "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2])


def _save_watermark(
    con: duckdb.DuckDBPyConnection,
    watermark: tuple[int, int, int],
) -> None:
    """Replace the watermark with the new value."""
    con.execute("DELETE FROM producer_state.matchup_revision_watermark")
    con.execute(
        "INSERT INTO producer_state.matchup_revision_watermark "
        "(game_pk, at_bat_number, pitch_number, updated_at) VALUES (?, ?, ?, ?)",
        [watermark[0], watermark[1], watermark[2], datetime.now(UTC)],
    )


def _read_signals(
    con: duckdb.DuckDBPyConnection,
    watermark: tuple[int, int, int] | None,
) -> Iterator[MatchupSignal]:
    """Yield MatchupSignal rows above the watermark, ordered for grouping.

    The ordering is (game_pk, at_bat_number, pitch_number, event_time).
    Grouping by the natural key triple then iterating produces
    consecutive emissions per pitch in event_time order, which is what
    detect_revision needs.
    """
    if watermark is None:
        where_clause = ""
        params: list[object] = []
    else:
        # Tuple comparison: emit signals where (game_pk, at_bat_number,
        # pitch_number) > watermark, lexicographically.
        where_clause = """
            WHERE (game_pk, at_bat_number, pitch_number) >
                  (?, ?, ?)
        """
        params = [watermark[0], watermark[1], watermark[2]]

    query = f"""
        SELECT
            event_time,
            game_pk,
            at_bat_number,
            pitch_number,
            pitcher_id,
            batter_id,
            handedness_matchup,
            signal_value,
            confidence_band,
            lineup_state_at_emission
        FROM silver.silver_matchup_signals
        {where_clause}
        ORDER BY game_pk, at_bat_number, pitch_number, event_time
    """

    for row in con.execute(query, params).fetchall():
        yield MatchupSignal(
            event_time=row[0],
            game_pk=row[1],
            at_bat_number=row[2],
            pitch_number=row[3],
            pitcher_id=row[4],
            batter_id=row[5],
            handedness_matchup=row[6],
            signal_value=row[7],
            confidence_band=row[8],
            lineup_state_at_emission=row[9],
        )


def run_producer(
    duckdb_path: Path | None = None,
    publisher: AvroEventPublisher | None = None,
    topic: str = DEFAULT_TOPIC,
    bootstrap_servers: str = DEFAULT_BOOTSTRAP,
    schema_registry_url: str = DEFAULT_SCHEMA_REGISTRY,
    dry_run: bool = False,
) -> ProducerStats:
    """Run one batch pass over silver_matchup_signals.

    Reads signals above the current watermark, groups by natural key,
    applies detect_revision over consecutive pairs per group, and
    publishes the resulting revisions. The watermark advances to the
    highest natural key seen at the end of the run (or stays put if
    no signals were read).

    dry_run=True skips publishing and watermark updates. Useful for
    development and CI smoke tests against a populated DuckDB.
    """
    duckdb_path = duckdb_path or DEFAULT_DUCKDB_PATH
    if not duckdb_path.exists():
        raise FileNotFoundError(f"DuckDB path {duckdb_path} does not exist. Run dbt build first.")

    log.info(
        "revision_producer.start",
        duckdb_path=str(duckdb_path),
        topic=topic,
        dry_run=dry_run,
    )

    con = duckdb.connect(str(duckdb_path), read_only=False)
    _ensure_watermark_table(con)
    watermark = _load_watermark(con)
    log.info("revision_producer.watermark.loaded", watermark=watermark)

    stats = ProducerStats()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # Group signals by natural key. The query is ordered so signals
    # within a key arrive consecutively; we collect them per key and
    # process when the key changes.
    current_key: tuple[int, int, int] | None = None
    current_group: list[MatchupSignal] = []
    max_key_seen: tuple[int, int, int] | None = None

    owns_publisher = False
    if publisher is None and not dry_run:
        publisher = AvroEventPublisher(
            bootstrap_servers=bootstrap_servers,
            schema_registry_url=schema_registry_url,
            client_id="revision-producer-batch",
        )
        owns_publisher = True

    try:
        for signal in _read_signals(con, watermark):
            stats.signals_read += 1
            key = (signal.game_pk, signal.at_bat_number, signal.pitch_number)

            if current_key is not None and key != current_key:
                # Key boundary: emit revisions for the previous group.
                stats.revisions_emitted += _process_group(
                    current_group,
                    publisher=publisher,
                    topic=topic,
                    run_id=run_id,
                    dry_run=dry_run,
                    stats=stats,
                )
                stats.groups_processed += 1
                current_group = []

            current_key = key
            current_group.append(signal)
            if max_key_seen is None or key > max_key_seen:
                max_key_seen = key

        # Final group.
        if current_group:
            stats.revisions_emitted += _process_group(
                current_group,
                publisher=publisher,
                topic=topic,
                run_id=run_id,
                dry_run=dry_run,
                stats=stats,
            )
            stats.groups_processed += 1

        if publisher is not None and not dry_run:
            publisher.flush(timeout=10.0)

        if max_key_seen is not None and not dry_run:
            _save_watermark(con, max_key_seen)
            stats.new_watermark = max_key_seen

    finally:
        if owns_publisher and publisher is not None:
            # AvroEventPublisher does not currently expose a close() —
            # flush is the closing operation. Already called above on
            # the success path.
            pass
        con.close()

    log.info(
        "revision_producer.complete",
        signals_read=stats.signals_read,
        groups_processed=stats.groups_processed,
        revisions_emitted=stats.revisions_emitted,
        no_op_pairs=stats.no_op_pairs,
        new_watermark=stats.new_watermark,
    )

    return stats


def _process_group(
    group: list[MatchupSignal],
    *,
    publisher: AvroEventPublisher | None,
    topic: str,
    run_id: str,
    dry_run: bool,
    stats: ProducerStats,
) -> int:
    """Compare consecutive signals in the group; emit revisions where warranted.

    Returns the count of revisions emitted from this group.
    """
    if len(group) < 2:
        # Single emission per natural key — nothing to revise.
        return 0

    emitted = 0
    for previous, new in pairwise(group):
        nk = f"{new.game_pk}:{new.at_bat_number}:{new.pitch_number}"
        source_event_id = f"batch_producer:{run_id}:{nk}"

        revision = detect_revision(
            previous_signal=previous,
            new_signal=new,
            source_event_id=source_event_id,
        )
        if revision is None:
            stats.no_op_pairs += 1
            continue

        if dry_run:
            emitted += 1
            continue

        if publisher is None:
            raise RuntimeError("Publisher must be provided when dry_run=False")

        # Partition key: the natural key triple. This keeps revisions
        # for the same pitch in the same partition so downstream
        # consumers see them in order.
        partition_key = nk
        publisher.publish(topic=topic, key=partition_key, event=revision)
        emitted += 1

    return emitted


def main() -> int:
    """CLI entry point. Run from the repo root."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Batch revision producer for matchup signal updates."
    )
    parser.add_argument(
        "--duckdb-path",
        type=Path,
        default=None,
        help="Path to dbt.duckdb. Defaults to ~/.bullpen/dbt.duckdb",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help="Kafka topic to publish revisions to.",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.environ.get("BULLPEN_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP),
    )
    parser.add_argument(
        "--schema-registry-url",
        default=os.environ.get("BULLPEN_SCHEMA_REGISTRY", DEFAULT_SCHEMA_REGISTRY),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute revisions without publishing or updating the watermark.",
    )
    args = parser.parse_args()

    stats = run_producer(
        duckdb_path=args.duckdb_path,
        topic=args.topic,
        bootstrap_servers=args.bootstrap_servers,
        schema_registry_url=args.schema_registry_url,
        dry_run=args.dry_run,
    )

    print(f"signals_read:       {stats.signals_read}")
    print(f"groups_processed:   {stats.groups_processed}")
    print(f"revisions_emitted:  {stats.revisions_emitted}")
    print(f"no_op_pairs:        {stats.no_op_pairs}")
    print(f"new_watermark:      {stats.new_watermark}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
