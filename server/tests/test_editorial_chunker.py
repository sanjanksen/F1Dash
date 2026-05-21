from editorial.chunker import chunk_text


def test_chunk_text_empty_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_short_text_single_chunk():
    text = "Lando Norris won the pole. Verstappen was second. Leclerc led the Ferrari charge."
    chunks = chunk_text(text, target_tokens=600)
    assert len(chunks) == 1
    assert "Lando Norris" in chunks[0]
    assert "Leclerc" in chunks[0]


def test_chunk_text_long_text_multiple_chunks():
    sentence = (
        "McLaren brought a major upgrade package to Imola and it visibly settled the car through the "
        "high-speed direction changes. "
    )
    body = sentence * 200  # ~3600 words -> well over 600 tokens
    chunks = chunk_text(body, target_tokens=600, overlap=80)
    assert len(chunks) >= 4
    for c in chunks:
        assert c.strip()


def test_chunk_text_has_overlap_between_consecutive_chunks():
    sentences = [f"Sentence number {i} talks about telemetry and pace at Suzuka." for i in range(120)]
    body = " ".join(sentences)
    chunks = chunk_text(body, target_tokens=200, overlap=60)
    assert len(chunks) >= 2
    first_tail = chunks[0].split(".")[-2].strip()  # last full sentence before terminal split
    assert first_tail and first_tail in chunks[1]
