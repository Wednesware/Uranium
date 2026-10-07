import json, platform, re, sys, subprocess, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from nitrogen import require
Color = require("mg.color").Color
from . import VERSION, URANIUM_DIR, Chunk, parse_commit_message, restore_last_verifiable_commit, worktree_is_tampered


THEME_COLOR: str = Color.coral
URANIUM_CHUNK: Chunk = Chunk("uranium")


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=URANIUM_DIR,
        capture_output=True,
        text=True,
        check=check,
    )


def _git_current_branch() -> str:
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode == 0:
        return branch.stdout.strip() or "main"
    return "main"


def _visible_width(text: str) -> int:
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _pad_visible(text: str, width: int) -> str:
    return text + (" " * max(0, width - _visible_width(text)))


def _format_history_timestamp(value: str, *, now: datetime | None = None) -> str:
    value = value.strip()
    if not value:
        return ""

    if now is None:
        now = datetime.now().astimezone()

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        timestamp = None
        for fmt in (
            "%Y-%m-%d %H:%M:%S %z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                timestamp = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue

    if timestamp is None:
        return value

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age = now.astimezone(timestamp.tzinfo) - timestamp.astimezone(timestamp.tzinfo)
    if age < timedelta(days=1):
        return timestamp.astimezone().strftime("%H:%M:%S")
    return timestamp.astimezone().strftime("%Y-%m-%d")


def _parse_history_subject(subject: str) -> tuple[str, str, str]:
    subject = subject.strip()
    if not subject:
        return "-", "-", ""

    try:
        parsed = parse_commit_message(subject)
    except ValueError:
        return "-", "-", subject.strip()

    action = parsed["operation"]
    if parsed["key"]:
        action = f"{action} {parsed['key']}"
    return parsed["machine"], parsed["chunk"], action


def _require_clean_worktree(operation: str) -> bool:
    if worktree_is_tampered(URANIUM_DIR):
        print(f"{THEME_COLOR}uranium:warning:{Color.reset} working tree differs from HEAD before {operation}; restoring the last verifiable commit.")
        restore_last_verifiable_commit(URANIUM_DIR)
    return True


def _format_history(limit: int = 20, cols: int = 1) -> str:
    proc = _git("log", "--pretty=format:%h%x00%aI%x00%s", "--max-count", str(limit), check=False)
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return "No commits yet."

    rows = []
    for index, line in enumerate(lines, 1):
        parts = line.split("\x00")
        if len(parts) < 3:
            commit = line[:7]
            timestamp = "-"
            subject = line
        else:
            commit = parts[0][:7]
            timestamp = _format_history_timestamp(parts[1].strip())
            subject = parts[2].strip()

        machine, chunk, action = _parse_history_subject(subject)
        rows.append((index, commit, timestamp, machine, chunk, action))

    widths = [
        max(len("COMMIT#"), max((len(row[1]) for row in rows), default=0)),
        max(len("TIMESTAMP"), max((len(row[2]) for row in rows), default=0)),
        max(len("MACHINE"), max((len(row[3]) for row in rows), default=0)),
        max(len("CHUNK"), max((len(row[4]) for row in rows), default=0)),
        max(len("ACTION"), max((len(row[5]) for row in rows), default=0)),
    ]

    header = [
        f"{Color.bold}{'COMMIT#'.ljust(widths[0])}{Color.reset}",
        f"{Color.bold}{'TIMESTAMP'.ljust(widths[1])}{Color.reset}",
        f"{Color.bold}{'MACHINE'.ljust(widths[2])}{Color.reset}",
        f"{Color.bold}{'CHUNK'.ljust(widths[3])}{Color.reset}",
        f"{Color.bold}{'ACTION'.ljust(widths[4])}{Color.reset}",
    ]
    rendered = [" - ".join(header)]
    for _, commit, timestamp, machine, chunk, action in rows:
        row = [
            f"{Color.cyan}{commit.ljust(widths[0])}{Color.reset}",
            f"{Color.gray}{timestamp.ljust(widths[1])}{Color.reset}",
            f"{Color.lime}{machine.ljust(widths[2])}{Color.reset}",
            f"{Color.yellow}{chunk.ljust(widths[3])}{Color.reset}",
            f"{THEME_COLOR}{Color.bold}{action.ljust(widths[4])}{Color.reset}",
        ]
        rendered.append(" - ".join(row))
    return "\n".join(rendered)


def _page_output(text: str, page: bool = False) -> None:
    if not page or not sys.stdout.isatty():
        print(text)
        return
    try:
        subprocess.run(["less", "-R"], input=text, text=True, check=False)
    except FileNotFoundError:
        print(text)


def _print_help() -> None:
    print(f"{THEME_COLOR}{Color.bold}Uranium v{VERSION}{Color.reset}")
    print(f"{Color.gray}Local and cloud-synced key-value storage for programs to persist non-sensitive user data.{Color.reset}")
    print("")
    print("Commands:")
    print(f"  {Color.bold}sync                         Synchronize local and cloud data{Color.reset}")
    print("  help                         Show this help message")
    print("  set <chunk>:<key>=<value>    Set or create an atom.")
    print("  get <chunk>:<key>            Retrieve an atom.")
    print("  data <chunk>:<key>=<value>   Retrieve an atom, creating it with a default value if it doesn't exist.")
    print("  rm <chunk>:<key>             Remove an atom.")
    print("  rmchunk <chunk>              Remove a chunk.")
    print("  ls                           List all chunks.")
    print("  ls <chunk>                   List all atoms in the base directory of a chunk.")
    print("  ls <chunk>:<key>             List all atoms under a specific key within a chunk.")
    print("  tree <chunk>                 Display the hierarchical structure of a chunk.")
    print("  tree <chunk>:<key>           Display the hierarchical structure under a specific key within a chunk.")
    print("  history [limit] [--page] [--cols N]  Show compact commit history; use --page to paginate and --cols to set the column count.")
    print("  rollback <commit>            Roll back the repository to the given commit.")

def _not_found_message(chunk_name: str, key: str | None = None) -> str:
    if key:
        return f"{THEME_COLOR}uranium:{Color.reset} '{chunk_name}:{key}' not found"
    return f"{THEME_COLOR}uranium:{Color.reset} '{chunk_name}' not found"

def sync(argv: list[str]) -> None:
    if not URANIUM_CHUNK.get("allow-sync", False):
        username = subprocess.check_output(
            ["gh", "api", "user", "--jq", ".login"],
            text=True
        ).strip()
        print(f"{THEME_COLOR}uranium:info:{Color.reset} allow uranium to create and manage a private repository ({username}/.uranium) on your behalf? this repository will be used to sync uranium data across your devices.")
        print(f"{THEME_COLOR}uranium:info:{Color.reset} full source code available at: https://github.com/Wednesware/Uranium")
        try:
            answer: str = input(f"(y/N): ")
            if "y" in answer.lower():
                if answer.lower() == "nay":
                    # protects Shakespeare from accidental confirmation of the sync operation
                    raise KeyboardInterrupt
                URANIUM_CHUNK["allow-sync"] = True
            else:
                raise KeyboardInterrupt
        except (KeyboardInterrupt, EOFError):
            print(f"\n{THEME_COLOR}uranium:info:{Color.reset} operation cancelled. nothing was done.")
            sys.exit(1)
    print(f"{THEME_COLOR}uranium:info:{Color.reset} synchronizing local and cloud data...")
    branch = _git_current_branch()
    machine = platform.node() or "uranium"
    repo_exists = subprocess.run(
        ["gh", "repo", "view", ".uranium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not repo_exists:
        print(f"{THEME_COLOR}  uranium:info:{Color.reset} no github repository found for '.uranium', creating one for you.")
        subprocess.run(
            ["gh", "repo", "create", ".uranium", "--private"],
            check=True,
        )
    if not _git("remote").stdout.strip():
        print(f"{THEME_COLOR}  uranium:info:{Color.reset} setting up git remote for '.uranium'.")
        repo_url = subprocess.run(
            ["gh", "repo", "view", ".uranium", "--json", "url", "--jq", ".url"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        _git("remote", "add", "origin", repo_url)

    _git("add", ".")
    if _git("status", "--porcelain").stdout.strip():
        note = {"version": 1, "machine": machine, "chunk": "sync", "operation": "sync", "key": ""}
        _git("-c", f"user.name=Uranium", "-c", "user.email=uranium@localhost", "commit", "-m", f"{machine}: [sync] sync")
        _git("notes", "--ref", "uranium", "add", "-f", "-m", json.dumps(note, separators=(",", ":")))

    _git("fetch", "origin")
    remote_branch = _git("rev-parse", "--verify", f"origin/{branch}", check=False)
    if remote_branch.returncode != 0:
        _git("push", "-u", "origin", branch)
        print(f"{THEME_COLOR}uranium:info:{Color.reset} sync complete.")
        return

    merge = _git("merge", f"origin/{branch}", "--no-edit", check=False)
    if merge.returncode != 0:
        conflicts = _git("diff", "--name-only", "--diff-filter=U").stdout.splitlines()
        if not conflicts:
            raise RuntimeError(f"Git merge failed:\n{merge.stderr.strip()}")
        print(f"{THEME_COLOR}uranium:warning:{Color.reset} local and cloud data conflict.")
        for file in conflicts:
            while True:
                choice = input(f"  {file}: keep [l]ocal or [c]loud? ").strip().lower()
                if choice in ("l", "local"):
                    _git("checkout", "--ours", "--", file)
                    break
                if choice in ("c", "cloud"):
                    _git("checkout", "--theirs", "--", file)
                    break
                print("  Please enter 'l' or 'c'.")
            _git("add", "--", file)
        note = {"version": 1, "machine": machine, "chunk": "sync", "operation": "resolve", "key": "conflicts"}
        _git("-c", f"user.name=Uranium", "-c", "user.email=uranium@localhost", "commit", "-m", f"{machine}: [sync] resolve conflicts")
        _git("notes", "--ref", "uranium", "add", "-f", "-m", json.dumps(note, separators=(",", ":")))

    _git("push", "origin", branch)
    print(f"{THEME_COLOR}uranium:info:{Color.reset} sync complete.")

def main(argv: list[str] | None = None) -> int:
    if not argv or argv[0] in ("help", "-h", "--help"):
        _print_help()
        return 0
    command = argv[0]
    match command:
        case "sync":
            if not _require_clean_worktree("sync"):
                return 1
            sync(argv[1:])
            return 0
        case "history":
            if not _require_clean_worktree("history"):
                return 1
            limit = 20
            page = False
            cols = 1
            index = 1
            while index < len(argv):
                arg = argv[index]
                if arg in ("--page", "page"):
                    page = True
                elif arg in ("--cols", "-c"):
                    if index + 1 >= len(argv):
                        print(f"{THEME_COLOR}uranium:{Color.reset} invalid history syntax: `u history [limit] [--page] [--cols N]`")
                        return 1
                    try:
                        cols = int(argv[index + 1])
                    except ValueError:
                        print(f"{THEME_COLOR}uranium:{Color.reset} invalid history syntax: `u history [limit] [--page] [--cols N]`")
                        return 1
                    if cols < 1:
                        print(f"{THEME_COLOR}uranium:{Color.reset} invalid history syntax: `u history [limit] [--page] [--cols N]`")
                        return 1
                    index += 1
                else:
                    try:
                        limit = max(1, int(arg))
                    except ValueError:
                        print(f"{THEME_COLOR}uranium:{Color.reset} invalid history syntax: `u history [limit] [--page] [--cols N]`")
                        return 1
                index += 1
            _page_output(_format_history(limit, cols=cols), page=page)
            return 0
        case "rollback":
            if not _require_clean_worktree("rollback"):
                return 1
            if len(argv) < 2:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid rollback syntax: `u rollback <commit>`")
                return 1
            target = argv[1]
            resolved = _git("rev-parse", "--verify", target, check=False)
            if resolved.returncode != 0:
                print(f"{THEME_COLOR}uranium:{Color.reset} commit '{target}' not found")
                return 1
            reset = _git("reset", "--hard", target, check=False)
            if reset.returncode != 0:
                print(f"{THEME_COLOR}uranium:{Color.reset} rollback failed: {reset.stderr.strip()}")
                return 1
            current = _git("log", "-1", "--pretty=format:%h %s")
            print(f"{THEME_COLOR}uranium:info:{Color.reset} rolled back to {current.stdout.strip()}")
            return 0
        case "set":
            if not _require_clean_worktree("set"):
                return 1
            try:
                key, value = argv[1].split("=", 1)
                chunk_name, key = key.split(":", 1)
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid set syntax: `u set <chunk>:<key>=<value>`")
                return 1
            chunk: Chunk = Chunk(chunk_name)
            if key == "chunk-info" and chunk._get_chunk_info() is not None:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to '{chunk_name}:{key}'")
                return 0
            if chunk.set(key, value):
                print(f"{THEME_COLOR}uranium:info:{Color.reset} set '{chunk_name}:{key}' = {value}")
            else:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to '{chunk_name}:{key}'")
            return 0
        case "get":
            if not _require_clean_worktree("get"):
                return 1
            try:
                chunk_name, key = argv[1].split(":", 1)
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid get syntax: `u get <chunk>:<key>`")
                return 1
            chunk: Chunk = Chunk(chunk_name)
            value = chunk.get(key, None)
            if value is not None:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} '{chunk_name}:{key}' = {value}")
            else:
                print(f"{THEME_COLOR}uranium:{Color.reset} '{chunk_name}:{key}' not found")
            return 0
        case "data":
            if not _require_clean_worktree("data"):
                return 1
            try:
                key, value = argv[1].split("=", 1)
                chunk_name, key = key.split(":", 1)
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid data syntax: `u data <chunk>:<key>=<value>`")
                return 1
            chunk: Chunk = Chunk(chunk_name)
            if key == "chunk-info" and chunk._get_chunk_info() is not None:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to '{chunk_name}:{key}'")
                return 0
            chunk_value: any = chunk.data(key, value)
            print(f"{THEME_COLOR}uranium:info:{Color.reset} data '{chunk_name}:{key}' = {chunk_value}")
            return 0
        case "rm":
            if not _require_clean_worktree("rm"):
                return 1
            try:
                chunk_name, key = argv[1].split(":", 1)
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid rm syntax: `u rm <chunk>:<key>`")
                return 1
            chunk: Chunk = Chunk(chunk_name)
            if key == "chunk-info":
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to '{chunk_name}:{key}'")
                return 0
            if chunk.rm(key):
                print(f"{THEME_COLOR}uranium:info:{Color.reset} removed '{chunk_name}:{key}'")
            else:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to '{chunk_name}:{key}'")
            return 0
        case "rmchunk":
            if not _require_clean_worktree("rmchunk"):
                return 1
            try:
                chunk_name = argv[1]
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid rmchunk syntax: `u rmchunk <chunk>`")
                return 1
            if Chunk.is_reserved_name(chunk_name):
                print(f"{THEME_COLOR}uranium:{Color.reset} cannot remove reserved chunk '{chunk_name}'")
                return 1
            chunk_path = URANIUM_DIR / chunk_name
            if not chunk_path.exists():
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to chunk '{chunk_name}'")
                return 0
            chunk: Chunk = Chunk(chunk_name, create=False)
            if chunk.rmchunk():
                print(f"{THEME_COLOR}uranium:info:{Color.reset} removed chunk '{chunk_name}'")
            else:
                print(f"{THEME_COLOR}uranium:info:{Color.reset} no changes made to chunk '{chunk_name}'")
            return 0
        case "ls":
            if not _require_clean_worktree("ls"):
                return 1
            if len(argv) == 1:
                chunks_dir: Path = URANIUM_DIR
                if not chunks_dir.exists():
                    return 0
                for item in sorted(chunks_dir.iterdir()):
                    if item.is_dir() and item.name != ".git":
                        chunk = Chunk(item.name, create=False)
                        info = chunk._get_chunk_info()
                        if info is not None and len(info) < 100:
                            print(f"{item.name} - {info}")
                        else:
                            print(item.name)
                return 0
            try:
                target = argv[1]
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid ls syntax: `u ls [chunk[:key]]`")
                return 1
            if ":" in target:
                chunk_name, key = target.split(":", 1)
                chunk: Chunk = Chunk(chunk_name, create=False)
                if not chunk.path.exists():
                    print(_not_found_message(chunk_name))
                    return 1
                if chunk._resolve_target(key) is None:
                    print(_not_found_message(chunk_name, key))
                    return 1
                for item in chunk.ls(key):
                    print(item)
                return 0
            chunk_name = target
            chunk: Chunk = Chunk(chunk_name, create=False)
            if not chunk.path.exists():
                print(_not_found_message(chunk_name))
                return 1
            for item in chunk.ls():
                if item == "chunk-info":
                    info = chunk._get_chunk_info()
                    if info is not None:
                        print(f"chunk-info - {info}")
                    else:
                        print(item)
                else:
                    print(item)
            return 0
        case "tree":
            if not _require_clean_worktree("tree"):
                return 1
            try:
                if ":" in argv[1]:
                    chunk_name, key = argv[1].split(":", 1)
                else:
                    chunk_name, key = argv[1], ""
            except Exception as err:
                print(f"{THEME_COLOR}uranium:{Color.reset} invalid tree syntax: `u tree <chunk>`")
                return 1
            chunk: Chunk = Chunk(chunk_name, create=False)
            if not chunk.path.exists():
                print(_not_found_message(chunk_name))
                return 1
            if key and chunk._resolve_target(key) is None:
                print(_not_found_message(chunk_name, key))
                return 1
            print(chunk.tree(key))
            return 0
        case _:
            print(f"{THEME_COLOR}uranium:{Color.reset} unknown command: {command}")
            _print_help()
            return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))