"""R8 regression test — `count_csv_rows_cols` must stream, not materialize.

Pre-R8 the function called `_decode_text(data)` on the full buffer before
sniffing the delimiter, producing a multi-MB Python string for a 10 MB
CSV. R3 cut the row-count to O(1) memory but left the upfront decode
in place. R8 sniffs the delimiter on an 8 KB head sample, then streams
the rest through `TextIOWrapper(BytesIO(data))` so the reader never
holds the full decoded string.

The correctness assertions ride alongside a peak-memory bound so a
"simpler" refactor that reintroduces the full-file decode fails here
instead of sneaking back into production.
"""

import tracemalloc

from ppxai.engine.file_preprocessing import count_csv_rows_cols


def _build_csv_bytes(rows: int, cols: int, delimiter: str = ",") -> bytes:
    """Deterministic CSV: header row + `rows` data rows, all ASCII."""
    header = delimiter.join(f"col{i}" for i in range(cols))
    body = "\n".join(
        delimiter.join(f"r{r}c{c}" for c in range(cols))
        for r in range(rows)
    )
    return f"{header}\n{body}\n".encode("utf-8")


class TestCountCsvRowsColsCorrectness:
    """Existing contract — row/col counts, delimiter detection, edge cases."""

    def test_empty_buffer_returns_zero(self):
        assert count_csv_rows_cols(b"") == (0, 0)

    def test_header_only_returns_zero_rows(self):
        data = b"a,b,c\n"
        assert count_csv_rows_cols(data) == (0, 3)

    def test_small_comma_csv(self):
        data = _build_csv_bytes(rows=5, cols=4)
        assert count_csv_rows_cols(data) == (5, 4)

    def test_tab_delimiter_detected(self):
        data = _build_csv_bytes(rows=3, cols=2, delimiter="\t")
        assert count_csv_rows_cols(data) == (3, 2)

    def test_semicolon_delimiter_detected(self):
        data = _build_csv_bytes(rows=4, cols=3, delimiter=";")
        assert count_csv_rows_cols(data) == (4, 3)

    def test_non_utf8_bytes_do_not_crash(self):
        """errors='replace' on TextIOWrapper keeps the reader alive."""
        # Valid header + a CP1252-byte in the body. UTF-8 decode inserts
        # U+FFFD where the byte is invalid; csv.reader still counts rows.
        data = b"name,value\nrow1," + b"\xff" + b"\n" + b"row2,ok\n"
        rows, cols = count_csv_rows_cols(data)
        assert rows == 2
        assert cols == 2

    def test_quoted_fields_with_embedded_newlines(self):
        data = b'name,bio\nalice,"line1\nline2"\nbob,hi\n'
        rows, _ = count_csv_rows_cols(data)
        # csv.reader treats the quoted newline as part of one row
        assert rows == 2

    def test_missing_trailing_newline(self):
        data = b"a,b\n1,2\n3,4"
        assert count_csv_rows_cols(data) == (2, 2)


class TestStreamingMemoryBound:
    """R8 — a 10 MB CSV must not allocate a 10 MB Python string."""

    def test_peak_memory_does_not_scale_with_file_size(self):
        """Run the counter on a 10 MB CSV under tracemalloc.

        The TODO's acceptance target is peak RSS growth under ~15 MB
        (buffer + decoded row, not a full decoded copy). We measure
        tracemalloc (not RSS) which excludes the input bytes that the
        test itself holds in scope — so the actual bound is tight:
        the counter's own allocations should stay well under 2 MB for
        a 10 MB input if it's streaming properly. Pre-R8 this peaked
        at ~20 MB because `_decode_text(data)` materialized the full
        file as a Python str.
        """
        data = _build_csv_bytes(rows=200_000, cols=5)
        assert len(data) >= 9 * 1024 * 1024  # sanity — at least 9 MB
        assert len(data) <= 12 * 1024 * 1024  # and not pathologically big

        tracemalloc.start()
        tracemalloc.reset_peak()
        rows, cols = count_csv_rows_cols(data)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Correctness first — so a regression here surfaces as a real
        # functional failure, not just a memory note.
        assert rows == 200_000
        assert cols == 5

        # R8 bound: peak allocations from the counter must stay under
        # ~2 MB even on a 10 MB input. If this fails, the likely cause
        # is re-introducing a full-file `_decode_text(data)` call.
        MB = 1024 * 1024
        assert peak < 2 * MB, (
            f"R8 regressed — peak allocation {peak / MB:.1f} MB on a "
            f"{len(data) / MB:.1f} MB CSV suggests full-file decode."
        )
