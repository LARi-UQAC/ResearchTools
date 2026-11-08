# Plan 1 - cube move notation

**Goal.** `scripts/moves.py` parses a move sequence from text, writes it back, and inverts it.

**Contents.** Numbered steps, each naming its file. Done means the tests pass and assert a failure path.

1. **Create `scripts/moves.py`.** Standard library only, pure functions, no printing. The module holds no test
   code.

2. **Add `parse(text) -> list`** splitting the text on whitespace and returning the list of moves. An empty text
   gives an empty list. A token that is not a face letter followed by nothing, an apostrophe or the digit 2 raises
   `ValueError` naming the token.

3. **Add `invert(moves) -> list`** returning the sequence that undoes the given one: the order is reversed, a move
   with an apostrophe loses it, a move without one gains it, and a half turn stays the same.

4. **Add `format_moves(moves) -> str`** joining the moves with single spaces.

5. **Write `scripts/Test/test_moves.py`**, following the test conventions of the spec. Cover: parsing a plain sequence;
   parsing apostrophe and half-turn moves; parsing an empty text; inverting a sequence and checking the result;
   inverting twice giving the original sequence; `format_moves` followed by `parse` giving the same list; and the
   failure path, an unknown token raising `ValueError`.

**Done when** `scripts/Test/test_moves.py` passes.
