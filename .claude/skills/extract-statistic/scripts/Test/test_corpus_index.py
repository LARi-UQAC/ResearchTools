"""
test_corpus_index.py - Offline unit tests for corpus_index.py.

No network, no model load, no database unless CORPUS_INDEX_DSN is set: the
embedder is injected as a deterministic fake, and the pgvector tests skip with a
clear message when no database is configured. Run with the project Python:
    python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus_index  # noqa: E402


LONG_TEXT = (
    "# Introduction\n\n"
    + "Le diagnostic industriel repose sur des mesures vibratoires. " * 40
    + "\n\n# Methode\n\n"
    + "Un reseau convolutif classe les signatures spectrales. " * 40
)


class TestChunker(unittest.TestCase):
    def test_a_short_text_is_one_chunk(self) -> None:
        chunks = corpus_index.chunk_text("Short body.", "otis2025diagnosis")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["passage"], "Short body.")

    def test_a_long_text_is_split_with_overlap(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertGreater(len(chunks), 1)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertLess(current["char_start"], previous["char_end"],
                            "consecutive chunks must overlap")

    def test_chunking_is_deterministic(self) -> None:
        first = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        second = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertEqual(first, second)

    def test_every_chunk_carries_its_citekey_and_offsets(self) -> None:
        for chunk in corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis"):
            self.assertEqual(chunk["citekey"], "otis2025diagnosis")
            self.assertLess(chunk["char_start"], chunk["char_end"])

    def test_the_passage_is_verbatim_from_the_source(self) -> None:
        for chunk in corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis"):
            self.assertEqual(LONG_TEXT[chunk["char_start"]:chunk["char_end"]],
                             chunk["passage"])

    def test_the_nearest_preceding_heading_is_recorded(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertEqual(chunks[0]["heading"], "Introduction")
        self.assertIn("Methode", {c["heading"] for c in chunks})

    def test_page_is_none_when_the_backend_gave_no_offsets(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis", page_offsets=None)
        self.assertTrue(all(c["page"] is None for c in chunks))

    def test_page_is_attributed_from_the_offsets_when_available(self) -> None:
        offsets = [0, len(LONG_TEXT) // 2]
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis", page_offsets=offsets)
        self.assertEqual(chunks[0]["page"], 1)
        self.assertEqual(chunks[-1]["page"], 2)

    def test_an_empty_text_yields_no_chunk(self) -> None:
        self.assertEqual(corpus_index.chunk_text("   \n  ", "otis2025diagnosis"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
