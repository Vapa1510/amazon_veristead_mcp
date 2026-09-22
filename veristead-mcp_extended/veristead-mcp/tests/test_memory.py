from veristead.tools import memory


def test_remember_and_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "test_memory.db")

    memory.remember("living room", "Lamp in the corner is the reading light")
    results = memory.recall_context_impl("living")

    assert len(results) == 1
    assert "reading light" in results[0]["detail"]


def test_recall_with_no_topic_returns_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "test_memory.db")

    memory.remember("topic-a", "first detail")
    memory.remember("topic-b", "second detail")

    results = memory.recall_context_impl()

    assert len(results) == 2


def test_forget_topic_removes_only_that_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "test_memory.db")

    memory.remember("routine:good night", "5 succeeded, 0 failed")
    memory.remember("routine:good night", "4 succeeded, 1 failed (Kitchen Light)")
    memory.remember("unrelated-topic", "should survive the forget call")

    result = memory.forget_topic_impl("routine:good night")
    remaining = memory.view_memory_impl()

    assert result["deleted"] == 2
    assert len(remaining) == 1
    assert remaining[0]["topic"] == "unrelated-topic"
