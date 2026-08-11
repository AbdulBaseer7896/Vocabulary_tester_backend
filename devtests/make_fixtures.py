"""Capture real API responses so the frontend can be tested against the
actual shapes the server returns, not hand-written guesses."""
import json
import os
import pathlib
import sys

import django

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
django.setup()

from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

c = Client()
root = pathlib.Path(__file__).resolve().parents[2]
fixtures = {}


def grab(path):
    r = c.get(path)
    fixtures[path] = json.loads(r.content)
    return fixtures[path]


# Two decks so the deck list has some variety.
for name in ("0001_field_notes.csv", "0002_market_day.csv"):
    with (root / "sample-decks" / name).open("rb") as fh:
        c.post("/api/decks/", {"file": fh, "name": name})

decks = grab("/api/decks/")["decks"]
deck_id = decks[0]["id"]
words = grab(f"/api/decks/{deck_id}/")["words"]

# A run that is left unfinished part-way, with timings.
r = c.post(
    "/api/sessions/",
    data=json.dumps({"deck": deck_id, "sort_order": "az", "reveal_mode": "each"}),
    content_type="application/json",
)
sid = r.json()["session"]["id"]
ordered = r.json()["words"]
for i in range(6):
    w = ordered[i]
    answers = {k: w[k] for k in ("word", "synonym1", "synonym2", "antonym1", "antonym2")}
    if i in (2, 4):
        answers["antonym1"] = "wrong guess"
    c.post(
        f"/api/sessions/{sid}/answer/",
        data=json.dumps({"index": i, "answers": answers, "plays": {"word": 2}, "elapsed_ms": 5000 + i * 2500}),
        content_type="application/json",
    )

grab(f"/api/sessions/{sid}/report/")
grab(f"/api/sessions/{sid}/")
# Resuming returns the same payload shape as fetching the session.
fixtures[f"/api/sessions/{sid}/resume/"] = fixtures[f"/api/sessions/{sid}/"]
grab(f"/api/decks/{deck_id}/sessions/")
grab("/api/sessions/history/")
grab("/api/decks/")

out = root / "frontend" / "test" / "fixtures.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"fixtures": fixtures, "sessionId": sid, "deckId": deck_id}, indent=1))
print(f"wrote {out} with {len(fixtures)} endpoints")
print("report keys:", sorted(fixtures[f"/api/sessions/{sid}/report/"].keys()))
print("history run keys:", sorted(fixtures["/api/sessions/history/"]["sessions"][0].keys()))

runner.teardown_databases(old_config)
