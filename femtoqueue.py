from os import makedirs, path, listdir, rename
from dataclasses import dataclass
from uuid import uuid4
import time

@dataclass
class FemtoTask:
    id: str
    data: bytes

class FemtoQueue:
    def __init__(
        self,
        data_dir: str,
        node_name: str,
        timeout_stale_ms: int = 30_000,
    ):
        assert node_name != "pending" \
           and node_name != "done" \
           and node_name != "failed"
        self.node_name = node_name

        assert timeout_stale_ms > 0
        self.timeout_stale_ms = timeout_stale_ms
        self.latest_stale_check_ts: float | None = None

        self.data_dir = data_dir
        self.dir_pending = path.join(data_dir, "pending")
        self.dir_in_progress = path.join(data_dir, node_name)
        self.dir_done = path.join(data_dir, "done")
        self.dir_failed = path.join(data_dir, "failed")

        makedirs(self.data_dir, exist_ok=True)
        makedirs(self.dir_pending, exist_ok=True)
        makedirs(self.dir_in_progress, exist_ok=True)
        makedirs(self.dir_done, exist_ok=True)
        makedirs(self.dir_failed, exist_ok=True)

    def push(self, data: bytes) -> str:
        now_us = 1_000_000 * time.time()
        id = f"{str(int(now_us))}_{uuid4().hex[-12:]}"
        pending_path = path.join(self.dir_pending, id)

        with open(pending_path, "wb") as f:
            f.write(data)

        return id

    def _release_stale_tasks(self):
        now = time.time()

        # Only run this every `timeout_stale_ms` milliseconds because iterating
        # through all tasks is slow
        timeout_sec = self.timeout_stale_ms / 1000.0
        if self.latest_stale_check_ts is not None and now - self.latest_stale_check_ts < timeout_sec:
            return
        self.latest_stale_check_ts = now

        for dir_name in listdir(self.data_dir):
            full_dir_path = path.join(self.data_dir, dir_name)

            # Skip non-directories and reserved names
            if not path.isdir(full_dir_path):
                continue
            if dir_name in ("pending", "done", "failed", self.node_name):
                continue

            # Check tasks in this node's in-progress directory
            for task_file in listdir(full_dir_path):
                task_path = path.join(full_dir_path, task_file)
                modified_time_us = int(task_file.split("_")[0])
                modified_time = modified_time_us / 1_000_000.0

                if now - modified_time < timeout_sec:
                    continue

                try:
                    pending_path = path.join(self.dir_pending, task_file)
                    rename(task_path, pending_path)
                except FileNotFoundError:
                    continue  # Task may have been moved by another node

    def _pop_task_path(self) -> str | None:
        # First check assigned tasks in progress
        tasks = listdir(self.dir_in_progress)
        if len(tasks) > 0:
            id = min(tasks)
            return path.join(self.dir_in_progress, id)

        # Then check pending tasks
        tasks = listdir(self.dir_pending)
        if len(tasks) > 0:
            id = min(tasks)
            return path.join(self.dir_pending, id)

        return None

    def pop(self) -> FemtoTask | None:
        self._release_stale_tasks()

        while True:
            task = self._pop_task_path()
            if task is None: return None

            id = path.basename(task)
            in_progress_path = path.join(self.dir_in_progress, id)

            try:
                rename(task, in_progress_path)
            except FileNotFoundError:
                # If another node grabbed the task, just get another one
                continue

            with open(in_progress_path, "rb") as f:
                content = f.read()
                return FemtoTask(id = id, data = content)

    def done(self, task: FemtoTask):
        in_progress_path = path.join(self.dir_in_progress, task.id)
        done_path = path.join(self.dir_done, task.id)

        try:
            rename(in_progress_path, done_path)
        except FileNotFoundError as e:
            raise Exception(f"Tried to complete a task that is not in progress, id={task.id}") from e

    def fail(self, task: FemtoTask):
        in_progress_path = path.join(self.dir_in_progress, task.id)
        failed_path = path.join(self.dir_failed, task.id)

        try:
            rename(in_progress_path, failed_path)
        except FileNotFoundError as e:
            raise Exception(f"Tried to fail a task that is not in progress, id={task.id}") from e
