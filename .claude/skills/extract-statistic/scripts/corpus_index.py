"""
corpus_index.py - Opt-in semantic index over a review corpus, for ad-hoc
cross-corpus retrieval only.

Four rules govern this module and none of them is negotiable:

  1. STRICTLY ADDITIVE. scan_sections() and scan_stats() in extract_text.py are
     not modified and remain the sole source for the statistics and future-works
     pipelines. This index never feeds them.
  2. Every hit returns citekey, page, and the verbatim passage, so a human
     verifies before use. This is the geolocalisation provenance contract.
  3. The build is OPT-IN and never runs implicitly inside another skill.
  4. A retrieval hit is NEVER a citation. A passage surfaced by similarity still
     passes the normal Scopus validation gate before entering any document. Every
     result carries that statement in its `note` field.

The embedder is an injected callable, so the tests run offline with a
deterministic fake and no model ever loads.

Usage:
  python corpus_index.py build  --bib <corpus.bib> [--refs <dir>] [--dsn ...]
  python corpus_index.py query  "<question>" [--top 8] [--dsn ...]
  python corpus_index.py status [--dsn ...]
"""

import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200

NOT_A_CITATION = (
    "Retrieved by similarity. This is provenance, not a citation: validate the "
    "reference through the scopus skill before it enters any document.")

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _headings(text: str) -> list[tuple[int, str]]:
    """Character offset and title of every Markdown heading, in order."""
    return [(m.start(), m.group(1).strip()) for m in _HEADING_RE.finditer(text)]


def _heading_at(headings: list[tuple[int, str]], offset: int) -> str:
    """The nearest heading at or before `offset`, or an empty string."""
    title = ""
    for start, name in headings:
        if start > offset:
            break
        title = name
    return title


def _page_at(page_offsets: list[int] | None, offset: int) -> int | None:
    """The 1-based page containing `offset`, or None when unknown."""
    if not page_offsets:
        return None
    page = 1
    for index, start in enumerate(page_offsets, start=1):
        if start > offset:
            break
        page = index
    return page


def chunk_text(text: str, citekey: str,
               page_offsets: list[int] | None = None) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split one document's cached text into overlapping windows, each carrying
        the provenance a human needs to verify a hit: citekey, character range,
        page when knowable, the nearest preceding heading, and the verbatim
        passage.

        The split is deterministic: fixed window, fixed overlap, no randomness
        and no tokenizer, so the same text yields identical chunks everywhere.

    Inputs:
        text (str): the cached document text
        citekey (str): the BibTeX key of the source
        page_offsets (list[int] | None): character offset where each page starts,
            when the parse backend reported it

    Outputs:
        chunks (list[dict]): {citekey, chunk_index, char_start, char_end, page,
        heading, passage}; empty when the text is blank
    --------------------------------------------------------------------------
    """
    if not text or not text.strip():
        return []

    headings = _headings(text)
    step = max(1, CHUNK_CHARS - CHUNK_OVERLAP)
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        chunks.append({
            "citekey": citekey,
            "chunk_index": index,
            "char_start": start,
            "char_end": end,
            "page": _page_at(page_offsets, start),
            "heading": _heading_at(headings, start),
            "passage": text[start:end],
        })
        if end >= len(text):
            break
        start += step
        index += 1
    return chunks


Embedder = Callable[[list[str]], list[list[float]]]

DEFAULT_EMBED_MODEL = "nomic-embed-text"
# Loopback only. No corpus text leaves the machine, so there is no cloud
# embedding vendor and no data-residency question under Law 25.
DEFAULT_EMBED_ENDPOINT = "http://127.0.0.1:11434/api/embed"
DEFAULT_BATCH_SIZE = 16


def ollama_embedder(model: str = DEFAULT_EMBED_MODEL,
                    endpoint: str = DEFAULT_EMBED_ENDPOINT) -> Embedder:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the default embedder: the local Ollama HTTP endpoint the repo
        already runs for local-writer and local-coder.

    Inputs:
        model (str): the local embedding model
        endpoint (str): the loopback embedding endpoint

    Outputs:
        embed (Embedder): texts to vectors

    Raises (at call time):
        RuntimeError with an actionable message when Ollama is unreachable.
    --------------------------------------------------------------------------
    """
    import requests

    def embed(texts: list[str]) -> list[list[float]]:
        try:
            response = requests.post(endpoint, json={"model": model, "input": texts},
                                     timeout=120)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"the local embedder at {endpoint} is unreachable: {exc}. Start "
                f"Ollama and pull the model with: ollama pull {model}") from exc
        payload = response.json()
        vectors = payload.get("embeddings") or payload.get("data") or []
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"the embedder returned {len(vectors)} vector(s) for {len(texts)} input(s)")
        return [list(map(float, v)) for v in vectors]

    return embed


def embed_chunks(chunks: list[dict[str, Any]], embedder: Embedder,
                 batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Embed every chunk, in batches, preserving order so vector i belongs to
        chunk i.

    Inputs:
        chunks (list[dict]): as returned by chunk_text
        embedder (Embedder): the injected embedding callable
        batch_size (int): how many passages per call

    Outputs:
        vectors (list[list[float]]): one vector per chunk, in order
    --------------------------------------------------------------------------
    """
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), max(1, batch_size)):
        window = [c["passage"] for c in chunks[start:start + batch_size]]
        vectors.extend(embedder(window))
    return vectors


def resolve_dsn(explicit: str | None = None) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the Postgres connection string, preferring an explicit value.

    Inputs:
        explicit (str | None): a value from the command line

    Outputs:
        dsn (str | None): the connection string, or None when unconfigured
    --------------------------------------------------------------------------
    """
    return explicit or os.environ.get("CORPUS_INDEX_DSN") or None


class VectorStore:
    """
    The pgvector store. It rides the Postgres RT-5's compose already runs, so no
    vector vendor is introduced. Every stored row keeps the provenance the
    retrieval contract requires.
    """

    def __init__(self, dsn: str, table: str = "corpus_chunks") -> None:
        self.dsn = dsn
        # The table name is a code-controlled identifier, never user input; it is
        # validated here so it can be interpolated into DDL safely.
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", table):
            raise ValueError(f"invalid table name: {table!r}")
        self.table = table

    def _connect(self):
        """
        ----------------------------------------------------------------------
        Purpose:
            Open the Postgres connection, importing psycopg lazily so its
            absence costs nothing until a store is actually used.

        Inputs:
            none.

        Outputs:
            connection (psycopg.Connection)

        Raises:
            RuntimeError: psycopg is not installed, naming the fix, rather than
                a bare ModuleNotFoundError - the requirements.txt comment
                promises the index 'reports itself unavailable', which a raw
                traceback does not.
        ----------------------------------------------------------------------
        """
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is not installed: run pip install -r "
                ".claude/skills/extract-statistic/scripts/requirements.txt") from exc
        return psycopg.connect(self.dsn)

    def ensure_schema(self, dim: int) -> None:
        """
        ----------------------------------------------------------------------
        Purpose:
            Create the extension, the table, and the similarity index.

        Inputs:
            dim (int): embedding dimension

        Outputs:
            none
        ----------------------------------------------------------------------
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    citekey     text NOT NULL,
                    chunk_index int  NOT NULL,
                    char_start  int  NOT NULL,
                    char_end    int  NOT NULL,
                    page        int,
                    heading     text,
                    passage     text NOT NULL,
                    embedding   vector({dim}) NOT NULL,
                    indexed_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (citekey, chunk_index)
                )""")
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {self.table}_embedding_idx
                ON {self.table} USING hnsw (embedding vector_cosine_ops)""")
            conn.commit()

    def upsert(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> int:
        """
        ----------------------------------------------------------------------
        Purpose:
            Store or replace the chunks of one or more documents. Re-indexing a
            document overwrites its rows rather than duplicating them.

        Inputs:
            chunks (list[dict]): as returned by chunk_text
            vectors (list[list[float]]): one vector per chunk, in order

        Outputs:
            written (int): number of rows written
        ----------------------------------------------------------------------
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunk(s) but {len(vectors)} vector(s)")
        rows = [(c["citekey"], c["chunk_index"], c["char_start"], c["char_end"],
                 c["page"], c["heading"], c["passage"],
                 "[" + ",".join(f"{v:.6f}" for v in vec) + "]")
                for c, vec in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {self.table}
                  (citekey, chunk_index, char_start, char_end, page, heading,
                   passage, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (citekey, chunk_index) DO UPDATE SET
                  char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end,
                  page = EXCLUDED.page, heading = EXCLUDED.heading,
                  passage = EXCLUDED.passage, embedding = EXCLUDED.embedding,
                  indexed_at = now()""", rows)
            conn.commit()
        logger.info("[CORPUS-INDEX] stored %d chunk(s)", len(rows))
        return len(rows)

    def search(self, vector: list[float], top: int) -> list[dict[str, Any]]:
        """
        ----------------------------------------------------------------------
        Purpose:
            Return the nearest chunks by cosine distance, each with its full
            provenance and the standing reminder that a hit is not a citation.

        Inputs:
            vector (list[float]): the query embedding
            top (int): how many hits

        Outputs:
            hits (list[dict]): {citekey, page, heading, char_start, char_end,
            passage, distance, note}
        ----------------------------------------------------------------------
        """
        literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT citekey, chunk_index, char_start, char_end, page, heading,
                       passage, embedding <=> %s::vector AS distance
                FROM {self.table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""", (literal, literal, top))
            rows = cur.fetchall()
        return [{
            "citekey": r[0], "chunk_index": r[1], "char_start": r[2], "char_end": r[3],
            "page": r[4], "heading": r[5], "passage": r[6], "distance": float(r[7]),
            "note": NOT_A_CITATION,
        } for r in rows]

    def stats(self) -> dict[str, Any]:
        """Row and document counts, for the status command."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*), count(DISTINCT citekey) FROM {self.table}")
            chunks, documents = cur.fetchone()
        return {"table": self.table, "chunks": int(chunks), "documents": int(documents)}

    def drop(self) -> None:
        """Remove the table. Used by the tests, and by a deliberate rebuild."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table}")
            conn.commit()
