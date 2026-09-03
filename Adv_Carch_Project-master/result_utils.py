import ast
import os
from collections import Counter


STATUS_COMPLETE = "COMPLETE"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_MALFORMED = "MALFORMED"


def parse_occupancies(text):
    values = []
    for token in str(text).split(","):
        token = token.strip()
        if token:
            values.append(int(token))
    if not values:
        raise ValueError("At least one occupancy must be specified")
    return values


def classify_result_file(path, trials, occupancies, expected_miss_columns=None):
    if not os.path.exists(path):
        return STATUS_INCOMPLETE, f"missing file: {path}"

    rows = []
    miss_columns = expected_miss_columns
    try:
        with open(path, "r") as f:
            for line_no, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = ast.literal_eval(stripped)
                except Exception as exc:
                    return STATUS_MALFORMED, f"line {line_no}: cannot parse row: {exc}"
                if not isinstance(row, (list, tuple)) or len(row) < 3:
                    return STATUS_MALFORMED, f"line {line_no}: expected [occupancy, accesses, misses...]"
                try:
                    occupancy = int(row[0])
                    int(row[1])
                    [int(x) for x in row[2:]]
                except (TypeError, ValueError) as exc:
                    return STATUS_MALFORMED, f"line {line_no}: non-integer result field: {exc}"
                if miss_columns is None:
                    miss_columns = len(row) - 2
                elif len(row) - 2 != miss_columns:
                    return STATUS_MALFORMED, (
                        f"line {line_no}: inconsistent miss columns {len(row) - 2} != {miss_columns}"
                    )
                rows.append(occupancy)
    except OSError as exc:
        return STATUS_MALFORMED, str(exc)

    expected_rows = len(occupancies) * int(trials)
    if len(rows) != expected_rows:
        return STATUS_INCOMPLETE, f"row count {len(rows)} != expected {expected_rows}"

    counts = Counter(rows)
    expected_set = set(int(x) for x in occupancies)
    actual_set = set(counts)
    if actual_set != expected_set:
        return STATUS_INCOMPLETE, f"occupancies {sorted(actual_set)} != expected {sorted(expected_set)}"

    bad = {occ: counts[occ] for occ in expected_set if counts[occ] != int(trials)}
    if bad:
        return STATUS_INCOMPLETE, f"occupancy row counts {bad} != trials {trials}"

    return STATUS_COMPLETE, f"{len(rows)} valid rows"


def is_complete_result_file(path, trials, occupancies, expected_miss_columns=None):
    status, _ = classify_result_file(path, trials, occupancies, expected_miss_columns)
    return status == STATUS_COMPLETE


def atomic_write_result(path, write_fn):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        write_fn(f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
