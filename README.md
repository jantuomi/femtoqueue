# FemtoQueue

<a href="https://pypi.org/project/femtoqueue/">
<img alt="PyPI - Version" src="https://img.shields.io/pypi/v/femtoqueue"></a>

<a href="https://github.com/jantuomi/femtoqueue/actions/workflows/build-test-publish.yml">
<img alt="GitHub Actions Workflow Status" src="https://img.shields.io/github/actions/workflow/status/jantuomi/femtoqueue/build-test-publish.yml"></a>

Ever wanted a zero-dependency, filesystem-backed, lock-free, durable, concurrent, retrying task queue implementation? No?

## Example

```python
from femtoqueue import FemtoQueue, FemtoTask

q = FemtoQueue(data_dir = "fq", node_id = "node1")
q.push("foobar".encode("utf-8"))

while task := q.pop():
    # Do something with `task.data`
    q.done(task) # or q.fail(task)

print("All tasks processed")
```

## Installation

`femtoqueue` is available on [PyPI](https://pypi.org/project/femtoqueue/).

```bash
uv add femtoqueue # using uv
pip install femtoqueue # using pip
```

Or just chuck the `femtoqueue.py` file into your Python 3 project. There are no dependencies other than the standard library.

## Features

This mini-library provides the `FemtoQueue` class with the standard queue interface:

| Method                     | Description                         |
| :------------------------- | :---------------------------------- |
| `push(task: bytes) -> str` | Add a task to the queue, returns id |
| `pop() -> FemtoTask`       | Get a task from the queue           |

Each task corresponds to one file in the `data_dir` directory. State changes are atomic since they use `rename()`. The task can contain whatever you want, the queue does not inspect it in any way.

Each concurrent worker node (library user) must have a stable identifier `node_id`. This way workers can automatically retry a task if they unexpectedly crash in the middle of processing.

Stale tasks (i.e. in progress for too long) are moved back to `pending` automatically after a timeout is reached (default: 30s).

## But isn't this slow?

I wouldn't migrate away from your production queue system just yet, but this is faster than you'd expect. Easily fast enough for some small or medium project. Turns out, creating and renaming files is pretty snappy.

Running the microbenchmark `python benchmark_mini.py` on a Macbook Pro M1 reports around 4500 pushed tasks/sec and 400 popped tasks/sec. Most of the time is spent opening files. A heftier FreeBSD machine was able to reach 21000 pushed/sec and 7400 popped/sec. Note that these are not very scientific numbers.

## Unit tests

```bash
python test.py
```

## Author and license

Jan Tuomi <<jan@jantuomi.fi>>. Licensed under Apache-2.0. All rights reserved.
