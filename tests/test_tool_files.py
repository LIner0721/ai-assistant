from assistant.tools.base import RiskLevel
from assistant.tools.files import FilesTool


def make(tmp_path):
    tool = FilesTool()
    d = tmp_path
    (d / "a.txt").write_text("hello", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("world", encoding="utf-8")
    return tool, d


def test_read_file(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("read_file", {"path": str(d / "a.txt")})
    assert r.ok and r.output == "hello"


def test_write_file_creates_parents(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("write_file",
                     {"path": str(d / "x" / "y.txt"), "content": "新内容"})
    assert r.ok
    assert (d / "x" / "y.txt").read_text(encoding="utf-8") == "新内容"


def test_list_dir(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("list_dir", {"path": str(d)})
    assert r.ok
    assert "a.txt" in r.output and "sub/" in r.output


def test_search_files(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("search_files",
                     {"directory": str(d), "pattern": "*.txt"})
    assert r.ok
    assert "a.txt" in r.output and "b.txt" in r.output


def test_file_info_and_delete(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("file_info", {"path": str(d / "a.txt")})
    assert r.ok and "存在" in r.output
    r2 = tool.execute("delete_file", {"path": str(d / "a.txt")})
    assert r2.ok
    r3 = tool.execute("file_info", {"path": str(d / "a.txt")})
    assert "不存在" in r3.output


def test_move_file(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("move_file",
                     {"src": str(d / "a.txt"), "dst": str(d / "moved.txt")})
    assert r.ok
    assert (d / "moved.txt").exists() and not (d / "a.txt").exists()


def test_errors_return_not_ok(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("read_file", {"path": str(d / "nope.txt")})
    assert not r.ok and "nope.txt" in r.output


def test_risks(tmp_path):
    tool, d = make(tmp_path)
    by_name = {s.name: s.risk for s in tool.specs}
    assert by_name["read_file"] is RiskLevel.LOW
    assert by_name["delete_file"] is RiskLevel.HIGH
    assert by_name["write_file"] is RiskLevel.HIGH
