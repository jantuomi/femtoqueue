from typing import cast
import os
import time
import unittest
import json
from femtoqueue import FemtoQueue, FemtoTask
from tempfile import mkdtemp

class TestFemtoQueue(unittest.TestCase):
    def test_basic(self):
        dir = mkdtemp()
        q = FemtoQueue(data_dir = dir, node_name = "node1")

        # Add a JSON task
        some_data = json.dumps({ "foo": "bar" })
        q.push(some_data.encode("utf-8"))

        # The task should be in the queue with the correct payload
        task = q.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)
        parsed_data = json.loads(task.data.decode("utf-8"))
        self.assertEqual(parsed_data["foo"], "bar")

        # Mark the task as done
        q.done(task)

        # There should be no tasks available
        task = q.pop()
        self.assertIsNone(task)

    def test_aborted(self):
        dir = mkdtemp()
        q = FemtoQueue(data_dir = dir, node_name = "node1")

        # Add a JSON task
        some_data = json.dumps({ "foo": "bar" })
        q.push(some_data.encode("utf-8"))

        # The task should be in the queue with the correct payload
        task = q.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)
        parsed_data = json.loads(task.data.decode("utf-8"))
        self.assertEqual(parsed_data["foo"], "bar")

        # Simulate a fault and start over
        q = FemtoQueue(data_dir = dir, node_name = "node1")

        # The task should still be assigned to this node
        task = q.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)
        parsed_data = json.loads(task.data.decode("utf-8"))
        self.assertEqual(parsed_data["foo"], "bar")

        # Mark the task as done
        q.done(task)

        # There should be no tasks available
        task = q.pop()
        self.assertIsNone(task)

    def test_release_stale_tasks(self):
        dir = mkdtemp()

        # Node1 creates and claims the task
        q1 = FemtoQueue(data_dir=dir, node_name="node1", timeout_stale_ms=100)
        q1.push(b"stuck")
        task = q1.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)

        # Simulate the task becoming stale by changing mtime
        task_path = os.path.join(dir, "node1", task.id)
        old_time = time.time() - 9999
        os.utime(task_path, (old_time, old_time))

        # Now node2 should see the task as stale and reclaim it
        q2 = FemtoQueue(data_dir=dir, node_name="node2", timeout_stale_ms=100)
        revived_task = q2.pop()
        self.assertIsNotNone(revived_task)
        revived_task = cast(FemtoTask, revived_task)
        self.assertEqual(revived_task.data, b"stuck")
        self.assertEqual(revived_task.id, task.id)

    def test_mark_task_failed(self):
        dir = mkdtemp()
        q = FemtoQueue(data_dir=dir, node_name="node1")

        # Push and pop a task
        q.push(b"will fail")
        task = q.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)

        # Mark the task as failed
        q.fail(task)

        # Ensure the file now exists in the failed directory
        failed_path = os.path.join(dir, "failed", task.id)
        self.assertTrue(os.path.exists(failed_path))

        # The task should not reappear in pop
        self.assertIsNone(q.pop())

    def test_mark_task_done(self):
        dir = mkdtemp()
        q = FemtoQueue(data_dir=dir, node_name="node1")

        # Push and pop a task
        q.push(b"complete me")
        task = q.pop()
        self.assertIsNotNone(task)
        task = cast(FemtoTask, task)

        # Mark the task as done
        q.done(task)

        # Ensure the file is now in the 'done' directory
        done_path = os.path.join(dir, "done", task.id)
        self.assertTrue(os.path.exists(done_path))

        # The task should not be returned again
        self.assertIsNone(q.pop())

if __name__ == '__main__':
    unittest.main()
