# FemtoQueue

Ever wanted a zero-dependency, filesystem-backed, durable, concurrent, retrying task queue implementation? No?

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

Just chuck the `femtoqueue.py` file into your Python 3 project. There are no dependencies other than the standard library.

## Features

This mini-library provides the `FemtoQueue` class with the standard queue interface:

| Method                         | Description                         |
| :----------------------------- | :---------------------------------- |
| `push(task: FemtoTask) -> str` | Add a task to the queue, returns id |
| `pop() -> FemtoTask`           | Get a task from the queue           |

Each task corresponds to one file in the `data_dir` directory. State changes are atomic since they use `mv` (or its Python equivalent `os.rename`).

Each concurrent worker node (library user) must have a stable identifier `node_id`. This way workers can automatically retry a task if they unexpectedly crash in the middle of processing.

Stale tasks (i.e. in progress for too long) are moved back to `pending` automatically when a timeout is reached (default: 30s).

## But isn't this slow?

I wouldn't migrate away from your production queue system just yet, but this is faster than you'd expect. Easily fast enough for some small or medium project. Turns out, creating and renaming files is pretty snappy.

## Unit tests

```bash
python test.py
```

## Author and license

Jan Tuomi <<jan@jantuomi.fi>>. Licensed under AGPL 3.0. All rights reserved.
