"""Regression test for the 500 on POST /answer/.

A database carrying an `elapsed_ms NOT NULL` column that the models did not
know about made every answer insert fail with an IntegrityError. This checks
the column now exists in the schema, is always populated by the ORM, and that
the migration leaves an already-present column alone.
"""
import json
import os
import pathlib
import sys

import django

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
django.setup()

from django.db import connection  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

ok, fail = [], []


def check(label, condition, detail=""):
    (ok if condition else fail).append(label)
    print(("  PASS  " if condition else "  FAIL  ") + label + (f"  {detail}" if detail and not condition else ""))


# ---- the migrated schema matches the shape the reported database has
with connection.cursor() as cursor:
    cursor.execute("PRAGMA table_info(vocab_answer)")
    info = {row[1]: {"notnull": row[3], "default": row[4]} for row in cursor.fetchall()}

check("elapsed_ms column exists after migrating", "elapsed_ms" in info, sorted(info))
check("column is NOT NULL, as in the reported database", info.get("elapsed_ms", {}).get("notnull") == 1, info.get("elapsed_ms"))
check(
    "column carries no database default, so the ORM must supply one",
    info.get("elapsed_ms", {}).get("default") in (None, ""),
    info.get("elapsed_ms"),
)

# ---- answering a question no longer explodes
c = Client()
root = pathlib.Path(__file__).resolve().parents[2]
with (root / "sample-decks" / "0001_field_notes.csv").open("rb") as fh:
    c.post("/api/decks/", {"file": fh, "name": "0001_field_notes.csv"})
deck_id = c.get("/api/decks/").json()["decks"][0]["id"]

r = c.post(
    "/api/sessions/",
    data=json.dumps({"deck": deck_id, "sort_order": "az", "reveal_mode": "each"}),
    content_type="application/json",
)
sid = r.json()["session"]["id"]
ordered = r.json()["words"]
slots = ("word", "synonym1", "synonym2", "antonym1", "antonym2")

w = ordered[0]
r = c.post(
    f"/api/sessions/{sid}/answer/",
    data=json.dumps({"index": 0, "answers": {k: w[k] for k in slots}, "elapsed_ms": 7000}),
    content_type="application/json",
)
check("submitting an answer returns 200", r.status_code == 200, r.content[:300])

with connection.cursor() as cursor:
    cursor.execute("SELECT slot, elapsed_ms FROM vocab_answer WHERE question_index=0 ORDER BY id")
    rows = cursor.fetchall()
check("five answer rows written", len(rows) == 5, rows)
check("each row records the question's elapsed time", all(row[1] == 7000 for row in rows), rows)

# ---- a submission that sends no timing at all still saves
w = ordered[1]
r = c.post(
    f"/api/sessions/{sid}/answer/",
    data=json.dumps({"index": 1, "answers": {k: w[k] for k in slots}}),
    content_type="application/json",
)
check("answer without elapsed_ms still saves", r.status_code == 200, r.content[:300])
with connection.cursor() as cursor:
    cursor.execute("SELECT elapsed_ms FROM vocab_answer WHERE question_index=1")
    zeros = sorted(row[0] for row in cursor.fetchall())
check("missing timing stores zero, not null", zeros == [0] * 5, zeros)

# ---- the guard in the migration leaves an existing column alone
loader = MigrationLoader(connection)
migration = loader.disk_migrations[("vocab", "0003_answer_elapsed_ms")]
run_python = migration.operations[0].database_operations[0]
before_state = loader.project_state(("vocab", "0002_testsession_timings"))
try:
    with connection.schema_editor() as editor:
        run_python.code(before_state.apps, editor)
    check("re-running the migration on an existing column is harmless", True)
except Exception as exc:  # noqa: BLE001
    check("re-running the migration on an existing column is harmless", False, f"{type(exc).__name__}: {exc}")

with connection.cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM vocab_answer")
    surviving = cursor.fetchone()[0]
check("answers survive the re-run", surviving == 10, surviving)

# ---- the timing report still reads correctly
report = c.get(f"/api/sessions/{sid}/report/").json()
check("report totals the timings", report["timing"]["total_ms"] == 7000, report["timing"]["total_ms"])

print()
print(f"{len(ok)} passed, {len(fail)} failed")
for f in fail:
    print("  FAILED:", f)

runner.teardown_databases(old_config)
raise SystemExit(1 if fail else 0)
