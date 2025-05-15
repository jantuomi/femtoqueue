# A script that does some work. Useful for external benchmarking tools, e.g. hyperfine.
# Compare two commits like this:
#
# hyperfine --warmup 1 \
#   --command-name no_sync --prepare 'git checkout c8d45e8 && (rm -r data || true)' 'python3 benchmark_just_do_work.py data' \
#   --command-name sync --prepare 'git checkout b6c1a44 && (rm -r data || true)' 'python3 benchmark_just_do_work.py data' \
#   --cleanup 'rm -r data'

import argparse
from femtoqueue import FemtoQueue

def benchmark_femtoqueue(data_dir: str, num_tasks: int = 1000):
    queue = FemtoQueue(data_dir=data_dir, node_id="node1")

    data = b"x" * 100  # 100-byte payload

    for _ in range(num_tasks):
        queue.push(data)

    while True:
        task = queue.pop()
        if not task:
            break
        queue.done(task)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FemtoQueue: Just run some tasks for external benchmarking")
    parser.add_argument("data_dir", type=str, help="Data directory. Won't be cleaned up!")
    args = parser.parse_args()

    benchmark_femtoqueue(args.data_dir)
