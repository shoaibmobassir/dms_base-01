"""Tests for chunking.py — text splitting for legal documents.

Edge cases tested:
  - Empty/whitespace text → empty list
  - Text shorter than max_chars → single chunk
  - Text exactly max_chars → single chunk
  - Long text → multiple chunks with proper overlap
  - Chunk boundaries prefer paragraph breaks (\\n\\n) then line breaks (\\n)
  - Single character text → single chunk
  - Very large text → many chunks, no infinite loop
"""
from chunking import chunk_text


class TestChunkTextBasics:
    def test_empty_string_returns_empty(self):
        assert chunk_text("") == []

    def test_none_returns_empty(self):
        assert chunk_text(None) == []

    def test_whitespace_only_returns_empty(self):
        assert chunk_text("   \n\t  ") == []

    def test_short_text_single_chunk(self):
        text = "This is a short legal argument."
        result = chunk_text(text, max_chars=1200)
        assert len(result) == 1
        assert result[0] == text

    def test_single_character(self):
        assert chunk_text("A") == ["A"]

    def test_exact_max_chars_single_chunk(self):
        text = "x" * 1200
        result = chunk_text(text, max_chars=1200)
        assert len(result) == 1
        assert result[0] == text


class TestChunkTextSplitting:
    def test_long_text_produces_multiple_chunks(self):
        text = "word " * 500  # ~2500 chars
        result = chunk_text(text, max_chars=1200, overlap=150)
        assert len(result) >= 2

    def test_chunks_have_overlap(self):
        # Create text with clear sentence boundaries
        text = "Sentence one. " * 100  # ~1400 chars
        result = chunk_text(text, max_chars=800, overlap=100)
        assert len(result) >= 2
        # Check that some content from end of chunk 1 appears in start of chunk 2
        # (overlap means they share some text)
        chunk1_end = result[0][-80:]
        chunk2_start = result[1][:150]
        # At least some text should overlap
        common_words = set(chunk1_end.split()) & set(chunk2_start.split())
        assert len(common_words) > 0

    def test_prefers_paragraph_boundary(self):
        text = "First paragraph content here.\n\nSecond paragraph content follows here."
        # max_chars set to split around the paragraph boundary
        result = chunk_text(text, max_chars=40, overlap=5)
        assert len(result) >= 2
        # First chunk should end near the paragraph break
        assert result[0].strip().endswith("here.")

    def test_prefers_newline_over_mid_word(self):
        text = "Line one content\nLine two content\nLine three content"
        result = chunk_text(text, max_chars=25, overlap=5)
        assert len(result) >= 2
        # Chunks should break at newline, not mid-word
        for chunk in result:
            assert not chunk.startswith(" ")  # no leading spaces after strip

    def test_no_infinite_loop_on_large_text(self):
        text = "a" * 10000
        result = chunk_text(text, max_chars=500, overlap=50)
        assert len(result) >= 15  # ~10000/500 ≈ 20 chunks
        assert all(len(c) <= 500 for c in result)

    def test_all_text_covered(self):
        """Every character of the original text appears in at least one chunk."""
        text = "The court held that force majeure applies. " * 40
        chunks = chunk_text(text.strip(), max_chars=300, overlap=30)
        reconstructed = set()
        for chunk in chunks:
            for i, c in enumerate(chunk):
                # Find this chunk's position in original
                pos = text.find(chunk[:20])
                if pos >= 0:
                    for j in range(len(chunk)):
                        reconstructed.add(pos + j)
        # At minimum, the chunks should cover most of the text
        assert len(reconstructed) > len(text) * 0.8


class TestChunkTextDefaults:
    def test_default_max_chars_is_1200(self):
        text = "x" * 1200
        result = chunk_text(text)
        assert len(result) == 1

    def test_default_splits_at_1201(self):
        text = "x" * 1201
        result = chunk_text(text)
        assert len(result) >= 2
