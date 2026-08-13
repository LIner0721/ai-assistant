import json

from assistant.core.sessions import now_iso
from assistant.storage.db import Database


class TaskRecorder:
    def __init__(self, db: Database):
        self.db = db

    def record(self, session_id, task_id, step_no, tool, args, result,
               status) -> None:
        self.db.execute(
            "INSERT INTO task_steps (session_id, task_id, step_no, tool, "
            "args, result, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, task_id, step_no, tool,
             json.dumps(args, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False), status, now_iso()))
