#!/usr/bin/env python3
import argparse
import sys
import time

from sqlalchemy import func
from app.models import Alias
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Update alias notes and backfill flag"
)
parser.add_argument(
    "-s", "--start_alias_id", default=0, type=int, help="Initial alias_id"
)
parser.add_argument("-e", "--end_alias_id", default=0, type=int, help="Last alias_id")

args = parser.parse_args()
alias_id_start = args.start_alias_id
max_alias_id = args.end_alias_id
if max_alias_id == 0:
    max_alias_id = Session.query(func.max(Alias.id)).scalar()

print(f"Checking alias {alias_id_start} to {max_alias_id}")
step = 1000
noteSql = (
    "(note = 'Created through Proton' or note = 'Created through partner Proton' )"
)
el_query = f"SELECT id, note, flags from alias where id>=:start AND id < :end AND {noteSql} ORDER BY id ASC"
alias_query = f"UPDATE alias set note = NULL, flags = flags | :flag where id = :alias_id and {noteSql}"
updated = 0
start_time = time.time()
for batch_start in range(alias_id_start, max_alias_id, step):
    rows = Session.execute(el_query, {"start": batch_start, "end": batch_start + step})
    for row in rows:
        print(row)
        sys.exit(1)
        Session.execute(
            alias_query, {"alias_id": row[0], "flag": Alias.FLAG_PARTNER_CREATED}
        )
        Session.commit()
        updated += 1
    elapsed = time.time() - start_time
    time_per_alias = elapsed / (updated + 1)
    last_batch_id = batch_start + step
    remaining = max_alias_id - last_batch_id
    time_remaining = (max_alias_id - last_batch_id) * time_per_alias
    hours_remaining = time_remaining / 3600.0
    print(
        f"\rAlias {batch_start}/{max_alias_id} {updated} {hours_remaining:.2f}hrs remaining"
    )
print("")
