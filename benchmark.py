import time
import tempfile
import shutil
from femtoqueue import FemtoQueue, FemtoTask

def benchmark_femtoqueue(num_tasks: int = 1000):
    tmpdir = tempfile.mkdtemp()
    queue = FemtoQueue(data_dir=tmpdir, node_name="node1")

    data = b"x" * 100  # 100-byte payload

    print(f"Pushing {num_tasks} tasks...")
    start = time.time()
    for _ in range(num_tasks):
        queue.push(data)
    push_duration = time.time() - start
    print(f"Pushed in {push_duration:.4f}s ({num_tasks / push_duration:.2f} tasks/sec)")

    print("Processing tasks (pop + done)...")
    start = time.time()
    processed = 0
    while True:
        task = queue.pop()
        if not task:
            break
        queue.done(task)
        processed += 1
    process_duration = time.time() - start
    print(f"Processed in {process_duration:.4f}s ({processed / process_duration:.2f} tasks/sec)")

    shutil.rmtree(tmpdir)

if __name__ == "__main__":
    benchmark_femtoqueue(1000)
