from pathlib import Path

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

READ_LIMIT = 200 * 1024
SEARCH_LIMIT = 200


def _spec(name, desc, risk):
    return ToolSpec(name=name, description=desc,
                    parameters={"type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"]}, risk=risk)


class FilesTool(Tool):
    @property
    def specs(self):
        return [
            _spec("read_file", "读取文件内容（文本）。", RiskLevel.LOW),
            _spec("write_file", "写入/覆盖文件，自动创建父目录。",
                  RiskLevel.HIGH),
            _spec("list_dir", "列出目录内容（条目名 + f/d 标记）。",
                  RiskLevel.LOW),
            _spec("search_files", "按 glob 模式递归搜索文件。",
                  RiskLevel.LOW),
            _spec("file_info", "文件信息：存在性、大小、修改时间。",
                  RiskLevel.LOW),
            _spec("move_file", "移动/重命名文件。", RiskLevel.HIGH),
            _spec("copy_file", "复制文件。", RiskLevel.HIGH),
            _spec("delete_file", "删除文件。", RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            return {
                "read_file": self._read,
                "write_file": self._write,
                "list_dir": self._list,
                "search_files": self._search,
                "file_info": self._info,
                "move_file": self._move,
                "copy_file": self._copy,
                "delete_file": self._delete,
            }[name](args)
        except Exception as exc:
            return ToolResult(ok=False, output=f"操作失败: {exc}")

    def _read(self, a):
        p = Path(a["path"])
        data = p.read_text(encoding="utf-8", errors="replace")
        if len(data) > READ_LIMIT:
            data = data[:READ_LIMIT] + "\n…(内容过长，已截断)"
        return ToolResult(ok=True, output=data)

    def _write(self, a):
        p = Path(a["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        return ToolResult(ok=True, output=f"已写入 {p}")

    def _list(self, a):
        p = Path(a["path"])
        lines = []
        for item in sorted(p.iterdir()):
            lines.append(item.name + ("/" if item.is_dir() else ""))
        return ToolResult(ok=True, output="\n".join(lines) or "(空目录)")

    def _search(self, a):
        root = Path(a["directory"])
        found = [str(p) for p in root.rglob(a["pattern"])][:SEARCH_LIMIT]
        return ToolResult(ok=True,
                          output="\n".join(found) or "(无匹配)")

    def _info(self, a):
        p = Path(a["path"])
        if not p.exists():
            return ToolResult(ok=True, output=f"{p} 不存在")
        st = p.stat()
        return ToolResult(ok=True,
                          output=f"{p}: 存在, 大小 {st.st_size} 字节, "
                                 f"修改时间 {st.st_mtime:.0f}")

    def _move(self, a):
        src, dst = Path(a["src"]), Path(a["dst"])
        src.rename(dst)
        return ToolResult(ok=True, output=f"已移动 {src} -> {dst}")

    def _copy(self, a):
        import shutil
        src, dst = Path(a["src"]), Path(a["dst"])
        shutil.copy2(src, dst)
        return ToolResult(ok=True, output=f"已复制 {src} -> {dst}")

    def _delete(self, a):
        p = Path(a["path"])
        p.unlink()
        return ToolResult(ok=True, output=f"已删除 {p}")
