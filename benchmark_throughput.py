import time
import tempfile
import shutil
import argparse
from random import randint
from femtoqueue import FemtoQueue

def run_benchmark(duration_seconds: int, payload_size: int = 100):
    print(f"Running throughput benchmark for {duration_seconds} sec. See -h for help.")
    tmpdir = tempfile.mkdtemp()
    q = FemtoQueue(data_dir=tmpdir, node_name="node1")
    payload = b"x" * payload_size

    total_count = 0
    count_per_second = 0
    start_time = last_report_time = time.time()

    try:
        while True:
            now = time.time()
            if now - start_time >= duration_seconds:
                break

            # Push, pop, done, and delete task.
            # NOTE: one cycle must take way less than one second for the math to be accurate.
            n_pushed_tasks = randint(0, 50)
            for _ in range(n_pushed_tasks):
                q.push(payload)

            while task := q.pop():
                q.done(task)
                total_count += 1
                count_per_second += 1

            # Print per-second throughput
            if now - last_report_time >= 1.0:
                print(f"{int(now - start_time)}s: {count_per_second} tasks/sec")
                count_per_second = 0
                last_report_time = now

    finally:
        elapsed = time.time() - start_time
        print("Cleaning up...")
        shutil.rmtree(tmpdir)

    print(f"\nRan for {elapsed:.2f} seconds")
    print(f"Total tasks processed: {total_count}")
    print(f"Overall throughput: {total_count / elapsed:.2f} tasks/sec")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FemtoQueue throughput benchmark")
    parser.add_argument("--duration", type=int, help="Duration to run the benchmark (in seconds)", default=10, required=False)
    args = parser.parse_args()

    run_benchmark(args.duration)
