"""ETL-пайплайн: raw -> core за окно дат, справочники, структурированный лог."""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.engine import Connection

from etl.config import get_settings
from etl.db import connect
from etl.extract import ExtractReport, load_raw_window
from etl.load import CoreReport, build_core, refresh_body_groups, refresh_dim_cities

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EtlReport:
    extract: ExtractReport
    core: CoreReport

    @property
    def read_rows(self) -> int:
        return self.extract.read_rows

    @property
    def loaded(self) -> int:
        return self.core.loaded

    @property
    def quarantined(self) -> int:
        return self.core.quarantined

    @property
    def by_reason(self) -> dict:
        return self.core.by_reason


def run_etl(conn: Connection, start_date: date, end_date: date) -> EtlReport:
    log.info("ETL window start=%s end=%s", start_date, end_date)
    extract = load_raw_window(conn, start_date, end_date)
    core = build_core(conn, start_date, end_date)
    refresh_dim_cities(conn)
    refresh_body_groups(conn)
    log.info(
        "ETL done: read=%d loaded=%d quarantined=%d by_reason=%s",
        extract.read_rows,
        core.loaded,
        core.quarantined,
        core.by_reason,
    )
    return EtlReport(extract=extract, core=core)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Run ETL for a loading_date window")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    settings = get_settings()
    with connect(settings) as conn:
        report = run_etl(conn, args.start, args.end)
    print(
        f"ETL report: read={report.read_rows} loaded={report.loaded} "
        f"quarantined={report.quarantined} by_reason={report.by_reason}"
    )


if __name__ == "__main__":
    main()
