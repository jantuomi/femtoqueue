from os import makedirs, path, listdir, rename, urandom, fsync
from dataclasses import dataclass
import time
from typing import Generator


@dataclass
class FemtoTask:
    id: str
    data: bytes


class FemtoQueue:
    RESERVED_NAMES = [
        "creating",
        "pending",
        "done",
        "failed",
    ]

    def __init__(
        self,
        data_dir: str,
        node_id: str,
        timeout_stale_ms: int = 30_000,
        sync_after_write: bool = False,
    ):
        """
        Construct a FemtoQueue client.

        Parameters
        ----------
        data_dir : str
            Directory where data files are persisted
        node_id : str
            Stable identifier for this instance
        timeout_stale_ms : int, default 30_000
            Time in milliseconds after which clients can release in-progress tasks back to pending.
        sync_after_write : bool, default False
            Run fsync() after writes to ensure data is synced to disk. Useful if you're worried about sudden power loss.
            Setting this on will slow down writes. Not necessary on certain file systems, such as ZFS.
        """
        assert node_id not in self.RESERVED_NAMES
        self.node_id = node_id

        assert timeout_stale_ms > 0
        self.timeout_stale_ms = timeout_stale_ms
        self.latest_stale_check_ts: float | None = None

        self.sync_after_write = sync_after_write

        self.todo_cache: Generator[str, None, None] | None = None

        self.data_dir = data_dir
        self.dir_creating = path.join(data_dir, "creating")
        self.dir_pending = path.join(data_dir, "pending")
        self.dir_in_progress = path.join(data_dir, node_id)
        self.dir_done = path.join(data_dir, "done")
        self.dir_failed = path.join(data_dir, "failed")

        makedirs(self.data_dir, exist_ok=True)
        makedirs(self.dir_creating, exist_ok=True)
        makedirs(self.dir_pending, exist_ok=True)
        makedirs(self.dir_in_progress, exist_ok=True)
        makedirs(self.dir_done, exist_ok=True)
        makedirs(self.dir_failed, exist_ok=True)

    def _gen_increasing_uuid(self, time_us: int | None) -> str:
        if not time_us:
            time_us = int(1_000_000 * time.time())

        rand_bytes = urandom(8)
        return f"{str(time_us)}_{rand_bytes.hex}"

    def push(self, data: bytes, time_us: int | None = None) -> str:
        """
        Push a new task into the queue.

        Parameters
        ----------
        data : bytes
            A bytes object representing the task. For JSON, you can use `json.dumps(obj).encode("utf-8")`.
        time_us : int or None
            A timestamp in microseconds. If not None, the current time is used. Only past tasks are available with `pop()`.
            Future timestamps can be used to schedule tasks.

        Returns
        -------
        id : str
            The task identifier, i.e. the file name.
        """
        id = self._gen_increasing_uuid(time_us)
        creating_path = path.join(self.dir_creating, id)
        pending_path = path.join(self.dir_pending, id)

        with open(creating_path, "wb") as f:
            f.write(data)
            if self.sync_after_write:
                fsync(f)

        rename(creating_path, pending_path)

        return id

    def _release_stale_tasks(self):
        now = time.time()

        # Only run this every `timeout_stale_ms` milliseconds because iterating
        # through all tasks is slow
        timeout_sec = self.timeout_stale_ms / 1000.0
        if (
            self.latest_stale_check_ts is not None
            and now - self.latest_stale_check_ts < timeout_sec
        ):
            return

        self.latest_stale_check_ts = now

        for dir_name in listdir(self.data_dir):
            full_dir_path = path.join(self.data_dir, dir_name)

            # Skip non-directories and reserved names
            if not path.isdir(full_dir_path):
                continue
            if dir_name in self.RESERVED_NAMES + [self.node_id]:
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
        now_us = time.time() * 1_000_000

        def _only_past(task_name: str) -> bool:
            return int(task_name.split("_")[0]) <= now_us

        # Check cache
        if self.todo_cache:
            try:
                return next(self.todo_cache)
            except StopIteration:
                pass

        # If cache empty, then check assigned tasks in progress (aborted)
        self.todo_cache = (
            path.join(self.dir_in_progress, x)
            for x in sorted(filter(_only_past, listdir(self.dir_in_progress)))
        )
        try:
            return next(self.todo_cache)
        except StopIteration:
            pass

        # Then check pending tasks
        self.todo_cache = (
            path.join(self.dir_pending, x)
            for x in sorted(filter(_only_past, listdir(self.dir_pending)))
        )
        try:
            return next(self.todo_cache)
        except StopIteration:
            pass
        return None

    def pop(self) -> FemtoTask | None:
        """
        Pop the oldest available task from the queue, or `None` if empty.
        If previous task processing was aborted (process was terminated unexpectedly), this method will return that incomplete task,
        effectively providing retry capability. If not, this will return the oldest task from "pending" state, if one exists.

        Returns
        -------
        task : FemtoTask or None
        """
        self._release_stale_tasks()

        while True:
            task = self._pop_task_path()
            if task is None:
                return None

            id = path.basename(task)
            in_progress_path = path.join(self.dir_in_progress, id)

            try:
                rename(task, in_progress_path)
            except FileNotFoundError:
                # If another node grabbed the task, just get another one
                continue

            with open(in_progress_path, "rb") as f:
                content = f.read()
                return FemtoTask(id=id, data=content)

    def done(self, task: FemtoTask):
        """
        Move a task to "done" status.

        Parameters
        ----------
        task : FemtoTask
            The in-progress task instance.
        """
        in_progress_path = path.join(self.dir_in_progress, task.id)
        done_path = path.join(self.dir_done, task.id)

        try:
            rename(in_progress_path, done_path)
        except FileNotFoundError as e:
            raise Exception(
                f"Tried to complete a task that is not in progress, id={task.id}"
            ) from e

    def fail(self, task: FemtoTask):
        """
        Move a task to "failed" status.

        Parameters
        ----------
        task : FemtoTask
            The in-progress task instance.
        """
        in_progress_path = path.join(self.dir_in_progress, task.id)
        failed_path = path.join(self.dir_failed, task.id)

        try:
            rename(in_progress_path, failed_path)
        except FileNotFoundError as e:
            raise Exception(
                f"Tried to fail a task that is not in progress, id={task.id}"
            ) from e
