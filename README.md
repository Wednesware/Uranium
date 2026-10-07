[![Wednesware](wednesware.png)](https://wednesware.org)

# Uranium

Local and cloud-synced key-value storage for programs to persist non-sensitive user data.

## Dependencies

- Python 3.12+
- Nitrogen 26.62+ (`pip install wwn`)

## Installation

### Library only

> `n2 get uranium`

### Library & `u` command (recommended)

> `n2 get uranium && n2 get uranium`

## Quick start

### Python library

```python
from uranium import Chunk

chunk = Chunk("MyGame")
chunk.set("player.health", 100)
chunk.set("player.name", "Danny")

print(chunk.get("player.health"))
print(chunk.get("player.name"))
```

### CLI

```bash
python -m uranium set MyGame:player.health=100
python -m uranium set MyGame:player.name=Danny
python -m uranium get MyGame:player.health
python -m uranium ls
python -m uranium ls MyGame
python -m uranium tree MyGame
```

## CLI commands

```bash
python -m uranium sync
python -m uranium set <chunk>:<key>=<value>
python -m uranium get <chunk>:<key>
python -m uranium data <chunk>:<key>=<value>
python -m uranium rm <chunk>:<key>
python -m uranium rmchunk <chunk>
python -m uranium ls
python -m uranium ls <chunk>
python -m uranium ls <chunk>:<key>
python -m uranium tree <chunk>
python -m uranium tree <chunk>:<key>
python -m uranium history [limit] [--page] [--cols N]
python -m uranium rollback <commit>
python -m uranium help
```

- `sync` synchronizes the local Uranium repository with GitHub.
- `history [limit] [--page] [--cols N]` prints compact commit history; use `--page` for paged output and `--cols` to set the number of columns.
- `rollback <commit>` resets the repository to the specified commit.

## Library API

```python
from uranium import Chunk
```

### `Chunk(name: str, create: bool = True)`

Creates or opens a chunk in Uranium's local data directory. Each chunk is stored as a directory containing JSON files.

> `chunk = Chunk("MyGame")`

### Methods

#### `set(key: str, value: any) -> bool`

Writes an atom at a nested key path. Dot-separated keys create "compounds" (nested directories).

> `chunk.set("player.health", 100)`

#### `get(key: str, default=...) -> any`

Returns the atom stored under a key. If it does not exist, it returns the provided default or raises when no default is supplied.

> `chunk.get("player.health")`

#### `data(key: str, default=...) -> any`

> `chunk.data("player.health", 100)`

Returns the existing atom if present; otherwise creates it using the supplied default.

#### `rm(key: str) -> bool`

> `chunk.rm("player.health")`

Removes an atom at the specified key.

#### `rmchunk() -> bool`

Deletes the entire chunk.

> `chunk.rmchunk()`

#### `ls(key: str = "") -> list[str]`

Lists entries in the current chunk or under a nested key.

> `chunk.ls("player")`

#### `tree(key: str = "") -> str`

Returns a tree-style string view of a chunk or selected key subtree.

> `chunk.tree("player")`

#### `_get_chunk_info() -> str | None`

Returns the readable chunk description stored in a `chunk-info` entry, if one exists.

> `chunk._get_chunk_info()`

## Chunk metadata

A chunk may include a special `chunk-info` entry:

```python
chunk = Chunk("MyGame")
chunk.set("chunk-info", "Chunk for MyGame, created by Danny")
```

This is used for readable summaries in `ls` output and cannot be overwritten or deleted once created.

## Notes

- Data is stored as JSON files on disk.
- The storage directory is managed under the platform's standard application data location.
- The internal Git metadata directory is reserved and not exposed as a normal chunk in listings.
