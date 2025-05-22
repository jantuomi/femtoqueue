from os import makedirs, path, PathLike, listdir, rename, urandom, fsync
from dataclasses import dataclass
import time
from typing import Generator
from io import BufferedReader, BufferedWriter
from hashlib import md5


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
        "scheduled",
    ]

    def __init__(
        self,
        data_dir: PathLike | str,
        node_id: str,
        timeout_stale_ms: int = 30_000,
        sync_after_write: bool = False,
    ):
        """
        Construct a FemtoQueue client.

        Parameters
        ----------
        data_dir : os.PathLike or str
            Directory where data files are persisted
        node_id : str
            Stable identifier for this instance
        timeout_stale_ms : int, default 30_000
            Time in milliseconds after which clients can release in-progress tasks back to pending.
        sync_after_write : bool, default False
            Run fsync() after writes to ensure data is synced to disk. Useful if you're worried about sudden power loss,
            but note that integrity checks will discard invalid writes even when sync_after_write is off.
            Setting sync_after_write on will slow down writes. Not necessary on certain file systems, such as ZFS.
        """
        assert node_id not in self.RESERVED_NAMES
        self.node_id = node_id

        assert timeout_stale_ms > 0
        self.timeout_stale_ms = timeout_stale_ms
        self.latest_stale_check_ts_us: int | None = None

        self.sync_after_write = sync_after_write

        self.todo_cache: Generator[str, None, None] | None = None

        self.data_dir = data_dir
        self.dir_creating = path.join(data_dir, "creating")
        self.dir_pending = path.join(data_dir, "pending")
        self.dir_in_progress = path.join(data_dir, node_id)
        self.dir_done = path.join(data_dir, "done")
        self.dir_failed = path.join(data_dir, "failed")
        self.dir_scheduled = path.join(data_dir, "scheduled")

        makedirs(self.data_dir, exist_ok=True)
        makedirs(self.dir_creating, exist_ok=True)
        makedirs(self.dir_pending, exist_ok=True)
        makedirs(self.dir_in_progress, exist_ok=True)
        makedirs(self.dir_done, exist_ok=True)
        makedirs(self.dir_failed, exist_ok=True)
        makedirs(self.dir_scheduled, exist_ok=True)

        self.monotonic_time_started_us: int = int(time.monotonic() * 1_000_000)
        self.reference_time_us: int = self._resolve_reference_time_us()

        self.interval_check_scheduled_us = 1_000_000
        self.latest_scheduled_check_ts_us: int | None = None

    def _resolve_reference_time_us(self) -> int:
        tasks_pending = listdir(self.dir_pending)
        newest_ts_us = None
        for task_name in tasks_pending:
            ts_us = int(task_name.split("_")[0])
            if newest_ts_us is None or ts_us > newest_ts_us:
                newest_ts_us = ts_us

        if newest_ts_us is None:
            return int(time.time() * 1_000_000)
        else:
            return newest_ts_us

    def _monotonic_time_now_us(self) -> int:
        return (
            self.reference_time_us
            + int(time.monotonic() * 1_000_000)
            - self.monotonic_time_started_us
        )

    def _gen_increasing_uuid(self, time_us: int) -> str:
        rand_bytes = urandom(8)
        return f"{str(time_us)}_{rand_bytes.hex}"

    def _write_v1(self, f: BufferedWriter, data: bytes):
        version = (1).to_bytes(1, "little")  # 1 byte
        padding = (0).to_bytes(7, "little")  # 7 bytes
        hash = md5(data).digest()
        header = version + padding + hash
        f.write(header)
        f.write(data)

    def _read_v1(self, f: BufferedReader) -> bytes | None:
        version_bytes = f.read(1)
        if version_bytes is None or len(version_bytes) == 0:
            return None

        version = version_bytes[0]
        if version != 1:
            return None

        f.seek(8)
        stored_hash = f.read(16)
        if stored_hash is None or len(stored_hash) != 16:
            return None

        data = f.read()
        if data is None:
            return None

        data_hash = md5(data).digest()
        if data_hash != stored_hash:
            return None

        return data

    def schedule(self, data: bytes, time_us: int) -> str:
        """
        Schedule a new task to be pushed to the queue at the given timestamp.
        Upon calling `pop`, scheduled tasks whose timestamp is in the past (based on time-of-day clock, i.e. `time.time()`)
        will be moved to the end of the queue. Note that these events will get a different ID when moved.

        Parameters
        ----------
        data : bytes
            A bytes object representing the task. For JSON, you can use `json.dumps(obj).encode("utf-8")`.
        time_us : int
            A timestamp in microseconds.

        Returns
        -------
        id : str
            The task identifier, i.e. the file name.
        """
        id = self._gen_increasing_uuid(time_us)
        creating_path = path.join(self.dir_creating, id)
        scheduled_path = path.join(self.dir_scheduled, id)

        with open(creating_path, "wb") as f:
            self._write_v1(f, data)
            if self.sync_after_write:
                fsync(f)

        rename(creating_path, scheduled_path)

        return id

    def push(self, data: bytes) -> str:
        """
        Push a new task into the queue.

        Parameters
        ----------
        data : bytes
            A bytes object representing the task. For JSON, you can use `json.dumps(obj).encode("utf-8")`.

        Returns
        -------
        id : str
            The task identifier, i.e. the file name.
        """
        m_now_us = self._monotonic_time_now_us()
        id = self._gen_increasing_uuid(m_now_us)
        creating_path = path.join(self.dir_creating, id)
        pending_path = path.join(self.dir_pending, id)

        with open(creating_path, "wb") as f:
            self._write_v1(f, data)
            if self.sync_after_write:
                fsync(f)

        rename(creating_path, pending_path)

        return id

    def _release_stale_tasks(self, m_now_us: int):
        # Only run this every `timeout_stale_ms` milliseconds because iterating
        # through all tasks is slow
        timeout_us = self.timeout_stale_ms * 1_000
        if (
            self.latest_stale_check_ts_us is not None
            and m_now_us - self.latest_stale_check_ts_us < timeout_us
        ):
            return

        self.latest_stale_check_ts_us = m_now_us

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

                if m_now_us - modified_time_us < timeout_us:
                    continue

                try:
                    pending_path = path.join(self.dir_pending, task_file)
                    rename(task_path, pending_path)
                except FileNotFoundError:
                    continue  # Task may have been moved by another node

    def _trigger_scheduled_tasks(self, m_now_us: int):
        if (
            self.latest_scheduled_check_ts_us is not None
            and m_now_us - self.latest_scheduled_check_ts_us
            < self.interval_check_scheduled_us
        ):
            return

        self.latest_scheduled_check_ts_us = m_now_us

        w_now_us = int(time.time() * 1_000_000)  # wall clock time

        for task_file in listdir(self.dir_scheduled):
            scheduled_time_us = int(task_file.split("_")[0])

            if scheduled_time_us < w_now_us:
                scheduled_path = path.join(self.dir_scheduled, task_file)
                id = self._gen_increasing_uuid(m_now_us)
                try:
                    pending_path = path.join(self.dir_pending, id)
                    rename(scheduled_path, pending_path)
                except FileNotFoundError:
                    continue  # Task may have been moved by another node

    def _pop_task_path(self) -> str | None:
        # Check cache
        if self.todo_cache:
            try:
                return next(self.todo_cache)
            except StopIteration:
                pass

        # If cache empty, then check assigned tasks in progress (aborted)
        self.todo_cache = (
            path.join(self.dir_in_progress, x)
            for x in sorted(listdir(self.dir_in_progress))
        )
        try:
            return next(self.todo_cache)
        except StopIteration:
            pass

        # Then check pending tasks
        self.todo_cache = (
            path.join(self.dir_pending, x) for x in sorted(listdir(self.dir_pending))
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
        m_now_us = self._monotonic_time_now_us()
        self._release_stale_tasks(m_now_us)
        self._trigger_scheduled_tasks(m_now_us)

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
                data = self._read_v1(f)
                if data is None:
                    # Data was corrupted, skip
                    continue
                return FemtoTask(id=id, data=data)

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
