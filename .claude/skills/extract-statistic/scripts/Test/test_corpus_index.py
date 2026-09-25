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
import unittest.mock

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


def fake_embedder(dim: int = 8):
    """Deterministic embedder: no model, no network, stable across machines."""
    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = [0.0] * dim
            for position, char in enumerate(text):
                digest[position % dim] += (ord(char) % 17) / 100.0
            vectors.append(digest)
        return vectors
    return embed


class TestEmbedderSeam(unittest.TestCase):
    def test_the_fake_embedder_is_deterministic(self) -> None:
        embed = fake_embedder()
        self.assertEqual(embed(["hello"]), embed(["hello"]))

    def test_embed_chunks_returns_one_vector_per_chunk(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        vectors = corpus_index.embed_chunks(chunks, fake_embedder())
        self.assertEqual(len(vectors), len(chunks))
        self.assertEqual(len(vectors[0]), 8)

    def test_embed_chunks_batches_without_changing_the_order(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        one = corpus_index.embed_chunks(chunks, fake_embedder(), batch_size=1)
        many = corpus_index.embed_chunks(chunks, fake_embedder(), batch_size=100)
        self.assertEqual(one, many)

    def test_the_default_embedder_targets_the_local_endpoint_only(self) -> None:
        # No corpus text may leave the machine: the default endpoint is loopback.
        self.assertIn("127.0.0.1", corpus_index.DEFAULT_EMBED_ENDPOINT)


class TestVectorStoreImportGuard(unittest.TestCase):
    """No database needed: proves a missing psycopg surfaces an actionable
    message rather than a bare ModuleNotFoundError, per the requirements.txt
    comment promising the index 'simply reports itself unavailable'."""

    def test_a_missing_psycopg_raises_an_actionable_runtime_error(self) -> None:
        import builtins
        real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name == "psycopg":
                raise ImportError("simulated: psycopg not installed")
            return real_import(name, *args, **kwargs)

        store = corpus_index.VectorStore("postgresql://x/y")
        with unittest.mock.patch("builtins.__import__", side_effect=_blocked):
            with self.assertRaises(RuntimeError) as ctx:
                store._connect()
        self.assertIn("psycopg", str(ctx.exception))
        self.assertIn("requirements.txt", str(ctx.exception))


@unittest.skipUnless(
    os.environ.get("CORPUS_INDEX_DSN"),
    "CORPUS_INDEX_DSN is not set: skipping the pgvector store tests. Start the "
    "RT-5 compose stack and export "
    "CORPUS_INDEX_DSN=postgresql://uqac:...@127.0.0.1:5433/uqac to run them.")
class TestVectorStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = corpus_index.VectorStore(
            os.environ["CORPUS_INDEX_DSN"], table="corpus_chunks_test")
        self.store.ensure_schema(dim=8)
        self.chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.vectors = corpus_index.embed_chunks(self.chunks, fake_embedder())

    def tearDown(self) -> None:
        self.store.drop()

    def test_upsert_then_stats_counts_the_chunks(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        self.assertEqual(self.store.stats()["chunks"], len(self.chunks))

    def test_upserting_twice_does_not_duplicate(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        self.store.upsert(self.chunks, self.vectors)
        self.assertEqual(self.store.stats()["chunks"], len(self.chunks))

    def test_search_returns_provenance_not_a_conclusion(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        hits = self.store.search(self.vectors[0], top=3)
        self.assertTrue(hits)
        for hit in hits:
            self.assertIn("citekey", hit)
            self.assertIn("passage", hit)
            self.assertIn("page", hit)
            self.assertIn("char_start", hit)

    def test_the_verbatim_passage_survives_the_round_trip(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        hits = self.store.search(self.vectors[0], top=1)
        self.assertEqual(hits[0]["passage"], self.chunks[0]["passage"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
