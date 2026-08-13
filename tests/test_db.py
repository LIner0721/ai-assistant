from assistant.storage.db import Database


def test_migrate_creates_tables():
    db = Database(":memory:")
    db.migrate()
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "messages", "task_steps", "memories",
            "settings", "schema_version"} <= tables
    assert "memories_fts" in tables
    assert db.schema_version() == 2


def test_migrate_is_idempotent():
    db = Database(":memory:")
    db.migrate()
    db.migrate()
    assert db.schema_version() == 2


def test_execute_and_query():
    db = Database(":memory:")
    db.migrate()
    sid = "s1"
    db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, '2026-01-01', '2026-01-01')", (sid, "测试"))
    row = db.query_one("SELECT title FROM sessions WHERE id = ?", (sid,))
    assert row["title"] == "测试"
