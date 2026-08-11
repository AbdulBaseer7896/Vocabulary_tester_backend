import json

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .csv_import import normalize, parse_deck_csv
from .models import SLOT_LABELS, SLOTS, Answer, Deck, TestSession, Word


def body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


def error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def deck_brief(deck):
    last = deck.sessions.filter(status="finished").first()
    active = deck.sessions.filter(status="active").first()
    return {
        "id": deck.id,
        "name": deck.name,
        "word_count": deck.words.count(),
        "marks": deck.mark_counts(),
        "created_at": deck.created_at.isoformat(),
        "updated_at": deck.updated_at.isoformat(),
        "last_result": (
            {
                "correct": last.answers.filter(is_correct=True).count(),
                "total": last.answers.count(),
                "deck_total": last.total_slots,
                "finished_at": last.finished_at.isoformat() if last.finished_at else None,
            }
            if last
            else None
        ),
        "active_session": (
            {
                "id": active.id,
                "current_index": active.current_index,
                "total_questions": active.total_questions,
                "reveal_mode": active.reveal_mode,
                "sort_order": active.sort_order,
                "updated_at": active.updated_at.isoformat(),
            }
            if active
            else None
        ),
    }


# ---------------------------------------------------------------- decks


@csrf_exempt
@require_http_methods(["GET", "POST"])
def decks(request):
    if request.method == "GET":
        return JsonResponse({"decks": [deck_brief(d) for d in Deck.objects.all()]})

    upload = request.FILES.get("file")
    if not upload:
        return error("No file was sent. Attach the CSV as the 'file' field.")

    name = (request.POST.get("name") or upload.name or "deck.csv").strip()
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return error("That file is not UTF-8 text. Export it again as UTF-8 CSV.")

    rows, warnings = parse_deck_csv(text)
    if not rows:
        return JsonResponse(
            {
                "error": f"No usable rows in {name}.",
                "warnings": warnings
                or ["Check that the header row reads Word,Meaning,Example."],
            },
            status=400,
        )

    with transaction.atomic():
        deck, _created = Deck.objects.get_or_create(name=name)
        deck.original_csv = text
        deck.save()
        # Re-uploading the same filename replaces the old rows. Any half-finished
        # run points at word ids that no longer exist, so it is closed out.
        deck.sessions.filter(status="active").update(status="abandoned")
        deck.words.all().delete()
        Word.objects.bulk_create(
            [Word(deck=deck, position=i, **row) for i, row in enumerate(rows)]
        )

    return JsonResponse({"deck": deck_brief(deck), "warnings": warnings}, status=201)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def deck_detail(request, pk):
    deck = get_object_or_404(Deck, pk=pk)
    if request.method == "DELETE":
        deck.delete()
        return JsonResponse({"deleted": True})
    return JsonResponse(
        {**deck_brief(deck), "words": [w.as_dict() for w in deck.words.all()]}
    )


@require_http_methods(["GET"])
def deck_csv(request, pk):
    deck = get_object_or_404(Deck, pk=pk)
    response = HttpResponse(deck.original_csv, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{deck.name}"'
    return response


def real_runs(queryset):
    """Runs worth listing: anything answered, plus any run still open.

    A run that was opened and replaced before a single answer was typed carries
    no result, so it is left out rather than padding the history with blanks.
    """
    return (
        queryset.annotate(answer_count=Count("answers"))
        .filter(Q(answer_count__gt=0) | Q(status="active"))
        .select_related("deck")
    )


@require_http_methods(["GET"])
def deck_sessions(request, pk):
    deck = get_object_or_404(Deck, pk=pk)
    return JsonResponse(
        {"sessions": [s.summary() for s in real_runs(deck.sessions.all())[:50]]}
    )


@require_http_methods(["GET"])
def session_history(request):
    """Every run across every deck, newest first."""
    runs = real_runs(TestSession.objects.all())
    deck_id = request.GET.get("deck")
    if deck_id:
        runs = runs.filter(deck_id=deck_id)
    return JsonResponse({"sessions": [s.summary() for s in runs[:200]]})


# ---------------------------------------------------------------- study marks


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
def word_mark(request, pk):
    word = get_object_or_404(Word, pk=pk)
    mark = body(request).get("mark")
    if mark not in dict(Word.MARK_CHOICES):
        return error("mark must be one of: none, green, yellow, red.")
    word.mark = mark
    word.marked_at = timezone.now() if mark != "none" else None
    word.save(update_fields=["mark", "marked_at"])
    return JsonResponse({"word": word.as_dict(), "marks": word.deck.mark_counts()})


@csrf_exempt
@require_http_methods(["POST"])
def reset_marks(request, pk):
    deck = get_object_or_404(Deck, pk=pk)
    deck.words.all().update(mark="none", marked_at=None)
    return JsonResponse({"marks": deck.mark_counts()})


# ---------------------------------------------------------------- sessions


def session_payload(session):
    words = {w.id: w for w in Word.objects.filter(id__in=session.word_ids)}
    ordered = [words[i].as_dict() for i in session.word_ids if i in words]
    data = {"session": session.summary(), "words": ordered}
    if session.reveal_mode == "end" and session.status == "active":
        # Running score stays hidden until the run is finished.
        data["session"]["correct"] = None
    return data


@csrf_exempt
@require_http_methods(["POST"])
def create_session(request):
    payload = body(request)
    deck = get_object_or_404(Deck, pk=payload.get("deck"))
    sort_order = payload.get("sort_order", "az")
    reveal_mode = payload.get("reveal_mode", "each")
    if sort_order not in ("az", "za") or reveal_mode not in ("each", "end"):
        return error("sort_order must be az or za; reveal_mode must be each or end.")

    words = list(deck.words.all())
    if not words:
        return error("That deck has no words in it.")

    words.sort(key=lambda w: w.word.lower(), reverse=(sort_order == "za"))

    with transaction.atomic():
        deck.sessions.filter(status="active").update(status="abandoned")
        session = TestSession.objects.create(
            deck=deck,
            sort_order=sort_order,
            reveal_mode=reveal_mode,
            word_ids=[w.id for w in words],
        )
    return JsonResponse(session_payload(session), status=201)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def session_detail(request, pk):
    session = get_object_or_404(TestSession, pk=pk)
    if request.method == "DELETE":
        session.status = "abandoned"
        session.save(update_fields=["status"])
        return JsonResponse({"abandoned": True})
    return JsonResponse(session_payload(session))


@csrf_exempt
@require_http_methods(["POST"])
def submit_answer(request, pk):
    session = get_object_or_404(TestSession, pk=pk)
    if session.status != "active":
        return error("This run is already closed.", status=409)

    payload = body(request)
    index = payload.get("index", session.current_index)
    if index != session.current_index:
        return error(
            f"Out of step: the server is on question {session.current_index}.", status=409
        )
    if index >= len(session.word_ids):
        return error("No question left at that position.", status=409)

    word = get_object_or_404(Word, pk=session.word_ids[index])
    typed = payload.get("answers") or {}
    plays = payload.get("plays") or {}

    try:
        elapsed = int(payload.get("elapsed_ms") or 0)
    except (TypeError, ValueError):
        elapsed = 0
    # A tab left open overnight would otherwise report an eight-hour word.
    elapsed = max(0, min(elapsed, 60 * 60 * 1000))

    results = []
    with transaction.atomic():
        for slot in SLOTS:
            given = str(typed.get(slot, ""))[:300]
            expected = getattr(word, slot)
            correct = normalize(given) == normalize(expected)
            Answer.objects.update_or_create(
                session=session,
                question_index=index,
                slot=slot,
                defaults={
                    "word": word,
                    "given": given,
                    "expected": expected,
                    "is_correct": correct,
                    "plays": int(plays.get(slot, 0) or 0),
                    "elapsed_ms": elapsed,
                },
            )
            results.append(
                {
                    "slot": slot,
                    "label": SLOT_LABELS[slot],
                    "given": given,
                    "expected": expected,
                    "correct": correct,
                    "plays": int(plays.get(slot, 0) or 0),
                }
            )

        if elapsed:
            timings = dict(session.timings or {})
            timings[str(index)] = elapsed
            session.timings = timings

        session.current_index = index + 1
        finished = session.current_index >= len(session.word_ids)
        if finished:
            session.status = "finished"
            session.finished_at = timezone.now()
        session.save()

    correct_count, answered = session.score()
    response = {
        "finished": session.status == "finished",
        "current_index": session.current_index,
        "answered": answered,
        "total_ms": session.total_ms(),
    }
    if session.reveal_mode == "each":
        response["results"] = results
        response["example"] = word.example
        response["correct"] = correct_count
    else:
        # Nothing about this question comes back until the whole run is done.
        response["results"] = None
    return JsonResponse(response)


@csrf_exempt
@require_http_methods(["POST"])
def resume_session(request, pk):
    """Re-open a run that was left unfinished so it can be carried on."""
    session = get_object_or_404(TestSession, pk=pk)
    if session.is_complete:
        return error("That run is already finished — nothing left to answer.", status=409)

    with transaction.atomic():
        session.deck.sessions.filter(status="active").exclude(pk=session.pk).update(
            status="abandoned"
        )
        session.status = "active"
        session.finished_at = None
        session.save(update_fields=["status", "finished_at"])
    return JsonResponse(session_payload(session))


@csrf_exempt
@require_http_methods(["POST"])
def finish_session(request, pk):
    """Close a run for good. Reading results no longer does this on its own."""
    session = get_object_or_404(TestSession, pk=pk)
    if session.status == "active":
        session.status = "finished"
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at"])
    return JsonResponse(build_report(session))


@require_http_methods(["GET"])
def session_report(request, pk):
    """Results for any run, finished or not, without changing its status."""
    return JsonResponse(build_report(get_object_or_404(TestSession, pk=pk)))


def build_report(session):
    words = {w.id: w for w in Word.objects.filter(id__in=session.word_ids)}
    grouped = {}
    for answer in session.answers.select_related("word"):
        entry = grouped.setdefault(
            answer.question_index,
            {
                "word_id": answer.word_id,
                "word": answer.word.word,
                "example": answer.word.example,
                "mark": answer.word.mark,
                "slots": [],
            },
        )
        entry["slots"].append(answer.as_dict())

    entries = [grouped[k] for k in sorted(grouped)]
    correct, answered = session.score()
    return {
        "session": session.summary(),
        "correct": correct,
        "answered": answered,
        "total_slots": session.total_slots,
        "skipped_questions": max(0, len(session.word_ids) - len(entries)),
        "entries": entries,
        "timing": session.timing_report(),
        "can_continue": not session.is_complete,
        "unseen": [
            words[i].word for i in session.word_ids[session.current_index :] if i in words
        ],
    }
