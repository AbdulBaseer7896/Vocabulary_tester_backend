import csv
import io


def parse_deck_csv(text):
    """Turn CSV text into row dicts. Bad rows are skipped with a reason."""
    rows = []
    warnings = []

    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    for required in ("word", "meaning", "example"):
        if required not in headers:
            warnings.append(
                f"The header row has no {required.title()} column. Expected: Word,Meaning,Example."
            )
    if warnings:
        return [], warnings

    def get(row, key):
        for k, v in row.items():
            if k and k.strip().lower() == key:
                return (v or "").strip()
        return ""

    for i, raw in enumerate(reader):
        line = i + 2  # header is line 1
        word = get(raw, "word")
        meaning = get(raw, "meaning")
        example = get(raw, "example")

        if not word:
            warnings.append(f"Line {line}: the Word column is empty. Row skipped.")
            continue

        cut = meaning.find("---")
        if cut == -1:
            warnings.append(
                f"Line {line} ({word}): Meaning has no --- between synonyms and antonyms. Row skipped."
            )
            continue

        synonyms = [s.strip() for s in meaning[:cut].split(",") if s.strip()]
        antonyms = [s.strip() for s in meaning[cut + 3 :].split(",") if s.strip()]

        if len(synonyms) < 2 or len(antonyms) < 2:
            warnings.append(
                f"Line {line} ({word}): expected two synonyms and two antonyms, "
                f"found {len(synonyms)} and {len(antonyms)}. Row skipped."
            )
            continue

        rows.append(
            {
                "word": word,
                "synonym1": synonyms[0],
                "synonym2": synonyms[1],
                "antonym1": antonyms[0],
                "antonym2": antonyms[1],
                "example": example,
            }
        )

    return rows, warnings


def normalize(value):
    return " ".join(str(value or "").strip().lower().split())
