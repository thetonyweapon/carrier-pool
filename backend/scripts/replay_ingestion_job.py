"""Replay one reviewed dead-lettered ingestion job."""

import argparse

from app.database import SessionLocal
from app.ingestion.jobs import replay_dead_letter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    args = parser.parse_args()
    with SessionLocal() as session:
        job = replay_dead_letter(session, args.job_id)
        print(f"requeued ingestion job {job.id}")


if __name__ == "__main__":
    main()
