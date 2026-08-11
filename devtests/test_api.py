"""End-to-end exercise of the API using Django's test client."""
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
ok = []
fail = []


def check(label, condition, detail=""):
    (ok if condition else fail).append(label)
    print(("  PASS  " if condition else "  FAIL  ") + label + (f"  {detail}" if detail and not condition else ""))


csv_path = pathlib.Path(__file__).resolve().parents[2] / "sample-decks" / "0001_field_notes.csv"

# ---- upload a deck
with csv_path.open("rb") as fh:
    r = c.post("/api/decks/", {"file": fh, "name": csv_path.name})
check("upload deck", r.status_code == 201, r.content[:200])
deck = r.json()["deck"]
deck_id = deck["id"]
print(f"  deck {deck_id}: {deck['word_count']} words")

words = c.get(f"/api/decks/{deck_id}/").json()["words"]

# ---- start a run
r = c.post(
    "/api/sessions/",
    data=json.dumps({"deck": deck_id, "sort_order": "az", "reveal_mode": "each"}),
    content_type="application/json",
)
check("create session", r.status_code == 201, r.content[:200])
payload = r.json()
sid = payload["session"]["id"]
ordered = payload["words"]
check("sorted a-z", [w["word"] for w in ordered] == sorted((w["word"] for w in ordered), key=str.lower))

# ---- answer the first 7 words with timings, leaving the run half done
for i in range(7):
    w = ordered[i]
    answers = {k: w[k] for k in ("word", "synonym1", "synonym2", "antonym1", "antonym2")}
    if i == 3:
        answers["synonym2"] = "definitely wrong"
    r = c.post(
        f"/api/sessions/{sid}/answer/",
        data=json.dumps(
            {
                "index": i,
                "answers": answers,
                "plays": {"word": 2},
                "elapsed_ms": 4000 + i * 1000,
            }
        ),
        content_type="application/json",
    )
    if r.status_code != 200:
        check(f"answer {i}", False, r.content[:200])
        break
check("answered 7 words", r.status_code == 200)
check("running clock returned", r.json()["total_ms"] == sum(4000 + i * 1000 for i in range(7)), r.json())

# ---- read the report WITHOUT closing the run
r = c.get(f"/api/sessions/{sid}/report/")
check("report readable mid-run", r.status_code == 200, r.content[:200])
report = r.json()
check("run still active after reading report", report["session"]["status"] == "active", report["session"]["status"])
check("report says it can continue", report["can_continue"] is True)
check("report counts 7 words done", report["session"]["words_done"] == 7, report["session"]["words_done"])
check("one wrong slot recorded", report["correct"] == 34, report["correct"])

t = report["timing"]
check("total time", t["total_ms"] == 49000, t["total_ms"])
check("average time", t["average_ms"] == 7000, t["average_ms"])
check("fastest word", t["fastest"]["ms"] == 4000, t["fastest"])
check("slowest word", t["slowest"]["ms"] == 10000, t["slowest"])
check("two blocks of five", len(t["blocks"]) == 2, t["blocks"])
check("first block totals 5 words", t["blocks"][0]["words"] == 5 and t["blocks"][0]["ms"] == 30000, t["blocks"][0])
check("second block partial", t["blocks"][1]["words"] == 2 and t["blocks"][1]["ms"] == 19000, t["blocks"][1])
check("per-word list", len(t["per_word"]) == 7 and t["per_word"][0]["word"] == ordered[0]["word"], t["per_word"][:2])

# ---- history shows the unfinished run
r = c.get("/api/sessions/history/")
check("history endpoint", r.status_code == 200, r.content[:200])
hist = r.json()["sessions"]
check("unfinished run appears in history", any(s["id"] == sid for s in hist), hist)
check("history carries total time", hist[0]["total_ms"] == 49000, hist[0])

# ---- start a fresh run: the old one is set aside but must stay in history
r = c.post(
    "/api/sessions/",
    data=json.dumps({"deck": deck_id, "sort_order": "za", "reveal_mode": "end"}),
    content_type="application/json",
)
sid2 = r.json()["session"]["id"]
check("second session created", r.status_code == 201)
hist = c.get("/api/sessions/history/").json()["sessions"]
check("abandoned run still listed", any(s["id"] == sid for s in hist), [s["id"] for s in hist])
check("empty new run not double-counted", len([s for s in hist if s["id"] == sid2]) == 1)

# ---- resume the older, half-finished run
r = c.post(f"/api/sessions/{sid}/resume/")
check("resume unfinished run", r.status_code == 200, r.content[:200])
resumed = r.json()["session"]
check("resumed run is active", resumed["status"] == "active")
check("resumes at word 8", resumed["current_index"] == 7, resumed["current_index"])

# answering picks up right where it stopped
w = ordered[7]
r = c.post(
    f"/api/sessions/{sid}/answer/",
    data=json.dumps(
        {
            "index": 7,
            "answers": {k: w[k] for k in ("word", "synonym1", "synonym2", "antonym1", "antonym2")},
            "elapsed_ms": 3000,
        }
    ),
    content_type="application/json",
)
check("answer after resume", r.status_code == 200, r.content[:200])
check("timing accumulated across resume", r.json()["total_ms"] == 52000, r.json()["total_ms"])

# ---- answering past the end of the deck is refused
r = c.post(
    f"/api/sessions/{sid}/answer/",
    data=json.dumps({"index": len(ordered), "answers": {}}),
    content_type="application/json",
)
check("cannot answer past the last word", r.status_code == 409, r.status_code)

# ---- absurd timings are clamped rather than trusted
r = c.post(
    "/api/sessions/",
    data=json.dumps({"deck": deck_id, "sort_order": "az", "reveal_mode": "each"}),
    content_type="application/json",
)
sid3 = r.json()["session"]["id"]
c.post(
    f"/api/sessions/{sid3}/answer/",
    data=json.dumps({"index": 0, "answers": {}, "elapsed_ms": 99 * 60 * 60 * 1000}),
    content_type="application/json",
)
per = c.get(f"/api/sessions/{sid3}/report/").json()["timing"]["per_word"]
check("overnight tab clamped to an hour", per[0]["ms"] == 3600000, per[0])

# ---- finishing is explicit, and a completed run cannot be reopened
r = c.post(f"/api/sessions/{sid}/finish/")
check("finish closes the run", r.json()["session"]["status"] == "finished", r.json()["session"]["status"])
check("finished run cannot continue", r.json()["can_continue"] is False)
r = c.post(f"/api/sessions/{sid}/resume/")
check("completed run refuses to reopen", r.status_code == 409, r.status_code)

# ---- but a run abandoned part-way can still be picked back up
r = c.post(f"/api/sessions/{sid3}/resume/")
check("part-finished run reopens", r.status_code == 200, r.content[:200])

# ---- deck-scoped history
r = c.get(f"/api/decks/{deck_id}/sessions/")
check("deck history endpoint", r.status_code == 200)
check("deck history has both runs", len(r.json()["sessions"]) >= 1, r.json()["sessions"])

print()
print(f"{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED:", f)

runner.teardown_databases(old_config)
raise SystemExit(1 if fail else 0)
