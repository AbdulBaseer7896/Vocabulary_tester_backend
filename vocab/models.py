from django.db import models

SLOTS = ("word", "synonym1", "synonym2", "antonym1", "antonym2")

# Pace is reported in blocks of this many words, alongside the per-word times.
BLOCK_SIZE = 5

SLOT_LABELS = {
    "word": "Word",
    "synonym1": "Syn 1",
    "synonym2": "Syn 2",
    "antonym1": "Ant 1",
    "antonym2": "Ant 2",
}


class Deck(models.Model):
    """One uploaded CSV. The raw file text is kept so it can be re-downloaded."""

    name = models.CharField(max_length=200, unique=True)
    original_csv = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def mark_counts(self):
        counts = {"none": 0, "green": 0, "yellow": 0, "red": 0}
        for row in self.words.values("mark").annotate(n=models.Count("id")):
            counts[row["mark"]] = row["n"]
        return counts


class Word(models.Model):
    """One CSV row, exploded into the five things the quiz reads aloud."""

    MARK_CHOICES = [
        ("none", "Not reviewed"),
        ("green", "Known"),
        ("yellow", "Halfway"),
        ("red", "Struggling"),
    ]

    deck = models.ForeignKey(Deck, related_name="words", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)
    word = models.CharField(max_length=200)
    synonym1 = models.CharField(max_length=200)
    synonym2 = models.CharField(max_length=200)
    antonym1 = models.CharField(max_length=200)
    antonym2 = models.CharField(max_length=200)
    example = models.TextField(blank=True)
    mark = models.CharField(max_length=10, choices=MARK_CHOICES, default="none")
    marked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.word

    def as_dict(self):
        return {
            "id": self.id,
            "word": self.word,
            "synonym1": self.synonym1,
            "synonym2": self.synonym2,
            "antonym1": self.antonym1,
            "antonym2": self.antonym2,
            "example": self.example,
            "mark": self.mark,
        }


class TestSession(models.Model):
    """A run through a deck. Kept open so a half-finished run can be resumed."""

    SORT_CHOICES = [("az", "A to Z"), ("za", "Z to A")]
    REVEAL_CHOICES = [("each", "After every word"), ("end", "At the end")]
    STATUS_CHOICES = [
        ("active", "In progress"),
        ("finished", "Finished"),
        ("abandoned", "Abandoned"),
    ]

    deck = models.ForeignKey(Deck, related_name="sessions", on_delete=models.CASCADE)
    sort_order = models.CharField(max_length=2, choices=SORT_CHOICES, default="az")
    reveal_mode = models.CharField(max_length=4, choices=REVEAL_CHOICES, default="each")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    word_ids = models.JSONField(default=list)
    current_index = models.PositiveIntegerField(default=0)
    # {"0": 12480, "1": 9310} — milliseconds spent on each question, keyed by
    # its position in word_ids. Only counts time the question was on screen, so
    # walking away mid-run does not inflate it.
    timings = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.deck.name} · {self.get_status_display()}"

    @property
    def total_questions(self):
        return len(self.word_ids)

    @property
    def total_slots(self):
        return len(self.word_ids) * len(SLOTS)

    @property
    def is_complete(self):
        return self.current_index >= len(self.word_ids) and bool(self.word_ids)

    def score(self):
        answered = self.answers.count()
        correct = self.answers.filter(is_correct=True).count()
        return correct, answered

    def words_done(self):
        return self.answers.values("question_index").distinct().count()

    def timing_entries(self):
        """[(question index, milliseconds)] for every question that was timed."""
        entries = []
        for key, value in (self.timings or {}).items():
            try:
                index, ms = int(key), int(value)
            except (TypeError, ValueError):
                continue
            if ms > 0:
                entries.append((index, ms))
        entries.sort()
        return entries

    def total_ms(self):
        return sum(ms for _, ms in self.timing_entries())

    def timing_report(self):
        """Total, per-word, and per-block timings for the results screen."""
        entries = self.timing_entries()
        lookup = {w.id: w.word for w in Word.objects.filter(id__in=self.word_ids)}
        names = {i: lookup[wid] for i, wid in enumerate(self.word_ids) if wid in lookup}

        per_word = [
            {
                "index": index,
                "position": index + 1,
                "word": names.get(index, f"Word {index + 1}"),
                "ms": ms,
            }
            for index, ms in entries
        ]
        total = sum(ms for _, ms in entries)
        counted = len(entries)

        blocks = []
        if entries:
            last = entries[-1][0]
            for start in range(0, last + 1, BLOCK_SIZE):
                chunk = [ms for i, ms in entries if start <= i < start + BLOCK_SIZE]
                if not chunk:
                    continue
                block_total = sum(chunk)
                blocks.append(
                    {
                        "from": start + 1,
                        "to": min(start + BLOCK_SIZE, len(self.word_ids)),
                        "words": len(chunk),
                        "ms": block_total,
                        "average_ms": round(block_total / len(chunk)),
                    }
                )

        by_length = sorted(per_word, key=lambda e: e["ms"])
        return {
            "block_size": BLOCK_SIZE,
            "total_ms": total,
            "counted": counted,
            "average_ms": round(total / counted) if counted else 0,
            "fastest": by_length[0] if by_length else None,
            "slowest": by_length[-1] if by_length else None,
            "blocks": blocks,
            "per_word": per_word,
        }

    def summary(self):
        correct, answered = self.score()
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "deck_name": self.deck.name,
            "sort_order": self.sort_order,
            "reveal_mode": self.reveal_mode,
            "status": self.status,
            "current_index": self.current_index,
            "total_questions": self.total_questions,
            "total_slots": self.total_slots,
            "words_done": self.words_done(),
            "correct": correct,
            "answered": answered,
            "complete": self.is_complete,
            "total_ms": self.total_ms(),
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class Answer(models.Model):
    """One typed spelling for one slot of one word."""

    session = models.ForeignKey(TestSession, related_name="answers", on_delete=models.CASCADE)
    word = models.ForeignKey(Word, related_name="answers", on_delete=models.CASCADE)
    question_index = models.PositiveIntegerField(default=0)
    slot = models.CharField(max_length=20)
    given = models.CharField(max_length=300, blank=True)
    expected = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    plays = models.PositiveIntegerField(default=0)
    # How long the whole question took, copied onto each of its five rows so a
    # run's pace can be read back from the answers alone. The session's
    # `timings` map stays the source the results screen reads.
    elapsed_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["question_index", "id"]
        unique_together = [("session", "question_index", "slot")]

    def as_dict(self):
        return {
            "slot": self.slot,
            "label": SLOT_LABELS.get(self.slot, self.slot),
            "given": self.given,
            "expected": self.expected,
            "correct": self.is_correct,
            "plays": self.plays,
        }
