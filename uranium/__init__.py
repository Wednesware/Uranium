import os, platform, json, shutil, subprocess, re
from pathlib import Path

try:
    from nitrogen import require
except ImportError:  # pragma: no cover - optional UI dependency
    def require(_module: str):
        class _ColorFallback:
            reset = "\033[0m"
            bold = "\033[1m"
            gray = "\033[90m"
            coral = "\033[38;5;208m"
            lime = "\033[92m"
            yellow = "\033[93m"
            cyan = "\033[96m"

        class _FallbackModule:
            Color = _ColorFallback

        return _FallbackModule()

VERSION: str = "26.3"
RESERVED_CHUNK_NAMES: set[str] = {".git"}
URANIUM_GIT_NAME: str = "Uranium"
URANIUM_GIT_EMAIL: str = "uranium@localhost"
UNAUTHORIZED_GIT_NAME: str = "Unauthorized"
UNAUTHORIZED_GIT_EMAIL: str = "unauthorized@localhost"
URANIUM_NOTE_REF: str = "uranium"

def parse_commit_message(message: str) -> dict[str, str]:
    text = (message or "").strip()
    if not text:
        raise ValueError("commit message is empty")

    match = re.fullmatch(r"(?P<machine>[^:]+): \[(?P<chunk>[^\]]+)\] (?P<operation>\S+)(?: (?P<key>.+))?", text)
    if match is None:
        raise ValueError(f"invalid commit message: {message!r}")

    data = {
        "machine": match.group("machine"),
        "chunk": match.group("chunk"),
        "operation": match.group("operation"),
        "key": match.group("key") or "",
    }
    if data["operation"] not in {"set", "data", "rm", "rmchunk", "sync", "resolve"}:
        raise ValueError(f"unsupported Uranium operation: {data['operation']!r}")
    return data

def _ensure_git_identity() -> None:
    subprocess.run(["git", "config", "user.name", URANIUM_GIT_NAME], cwd=URANIUM_DIR, check=False, capture_output=True)
    subprocess.run(["git", "config", "user.email", URANIUM_GIT_EMAIL], cwd=URANIUM_DIR, check=False, capture_output=True)

def reset_git_identity_to_unauthorized(repo_dir: Path | None = None) -> None:
    repo_dir = repo_dir or URANIUM_DIR
    subprocess.run(["git", "config", "user.name", UNAUTHORIZED_GIT_NAME], cwd=repo_dir, check=False, capture_output=True)
    subprocess.run(["git", "config", "user.email", UNAUTHORIZED_GIT_EMAIL], cwd=repo_dir, check=False, capture_output=True)

def _create_commit_note(
    machine: str,
    chunk: str,
    operation: str,
    key: str = "",
    *,
    commit_hash: str = "",
    subject: str = "",
    author_name: str = "",
    author_email: str = "",
    committer_name: str = "",
    committer_email: str = "",
) -> dict[str, str | int]:
    note: dict[str, str | int] = {
        "version": 1,
        "machine": machine,
        "chunk": chunk,
        "operation": operation,
        "key": key,
    }
    if commit_hash:
        note["commit"] = commit_hash
    if subject:
        note["subject"] = subject
    if author_name:
        note["author_name"] = author_name
    if author_email:
        note["author_email"] = author_email
    if committer_name:
        note["committer_name"] = committer_name
    if committer_email:
        note["committer_email"] = committer_email
    return note


def repo_has_head(repo_dir: Path | None = None) -> bool:
    repo_dir = repo_dir or URANIUM_DIR
    status = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return status.returncode == 0


def _read_commit_note(commit_hash: str = "HEAD", repo_dir: Path | None = None) -> dict[str, object] | None:
    repo_dir = repo_dir or URANIUM_DIR
    status = subprocess.run(
        ["git", "notes", "--ref", URANIUM_NOTE_REF, "show", commit_hash],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or not status.stdout.strip():
        return None
    try:
        note = json.loads(status.stdout)
    except json.JSONDecodeError:
        return None
    return note if isinstance(note, dict) else None


def _expected_note_for_commit(
    commit_hash: str,
    author_name: str,
    author_email: str,
    committer_name: str,
    committer_email: str,
    subject: str,
) -> dict[str, str | int]:
    parsed = parse_commit_message(subject)
    return _create_commit_note(
        parsed["machine"],
        parsed["chunk"],
        parsed["operation"],
        parsed["key"],
        commit_hash=commit_hash,
        subject=subject,
        author_name=author_name,
        author_email=author_email,
        committer_name=committer_name,
        committer_email=committer_email,
    )


def _diff_summary_for_commit(commit_hash: str = "HEAD", repo_dir: Path | None = None) -> list[tuple[int, int, str]]:
    repo_dir = repo_dir or URANIUM_DIR
    status = subprocess.run(
        ["git", "diff-tree", "--root", "--no-commit-id", "-r", "--numstat", commit_hash],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        return []

    rows: list[tuple[int, int, str]] = []
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            added = int(parts[0])
            deleted = int(parts[1])
        except ValueError:
            continue
        path = parts[2]
        rows.append((added, deleted, path))
    return rows


def commit_matches_action(commit_hash: str = "HEAD", repo_dir: Path | None = None) -> bool:
    repo_dir = repo_dir or URANIUM_DIR
    status = subprocess.run(
        ["git", "show", "-s", "--format=%H%x00%s", commit_hash],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or not status.stdout.strip():
        return False

    parts = status.stdout.strip().split("\x00")
    if len(parts) != 2:
        return False

    commit_hash_value, subject = parts
    try:
        parsed = parse_commit_message(subject)
    except ValueError:
        return False

    diff_rows = _diff_summary_for_commit(commit_hash_value, repo_dir)
    if not diff_rows:
        return False

    operation = parsed["operation"]
    if operation in {"set", "data"}:
        return len(diff_rows) == 1 and (diff_rows[0][0] > 0 or diff_rows[0][1] > 0)
    if operation == "rm":
        return len(diff_rows) == 1 and diff_rows[0][0] == 0 and diff_rows[0][1] > 0
    if operation == "rmchunk":
        chunk_name = parsed["chunk"]
        if not diff_rows:
            return False
        for _, _, path in diff_rows:
            if path == chunk_name or path.startswith(f"{chunk_name}/"):
                continue
            return False
        return True
    if operation in {"sync", "resolve"}:
        return True
    return False


def commit_has_valid_note(commit_hash: str = "HEAD", repo_dir: Path | None = None) -> bool:
    repo_dir = repo_dir or URANIUM_DIR
    status = subprocess.run(
        ["git", "show", "-s", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%s", commit_hash],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or not status.stdout.strip():
        return False

    parts = status.stdout.strip().split("\x00")
    if len(parts) != 6:
        return False

    commit_hash_value, author_name, author_email, committer_name, committer_email, subject = parts
    try:
        expected = _expected_note_for_commit(
            commit_hash_value,
            author_name,
            author_email,
            committer_name,
            committer_email,
            subject,
        )
    except ValueError:
        return False

    note = _read_commit_note(commit_hash_value, repo_dir)
    if note is None:
        return False

    for key, value in expected.items():
        if note.get(key) != value:
            return False
    return commit_matches_action(commit_hash_value, repo_dir)


def head_is_uranium_commit(repo_dir: Path | None = None) -> bool:
    repo_dir = repo_dir or URANIUM_DIR
    if not repo_has_head(repo_dir):
        return False
    status = subprocess.run(
        ["git", "log", "-1", "--pretty=format:%H%x00%an%x00%ae%x00%cn%x00%ce%x00%s"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or not status.stdout.strip():
        return False

    parts = status.stdout.strip().split("\x00")
    if len(parts) != 6:
        return False

    commit_hash, author_name, author_email, committer_name, committer_email, subject = parts
    try:
        parse_commit_message(subject)
    except ValueError:
        return False

    if (
        author_name != URANIUM_GIT_NAME or author_email != URANIUM_GIT_EMAIL
        or committer_name != URANIUM_GIT_NAME or committer_email != URANIUM_GIT_EMAIL
    ):
        return False

    return commit_has_valid_note(commit_hash, repo_dir)


def latest_verifiable_commit(repo_dir: Path | None = None) -> str | None:
    repo_dir = repo_dir or URANIUM_DIR
    if not repo_has_head(repo_dir):
        return None
    status = subprocess.run(
        ["git", "log", "--pretty=format:%H%x00%an%x00%ae%x00%cn%x00%ce%x00%s"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        return None

    for line in status.stdout.splitlines():
        parts = line.split("\x00")
        if len(parts) != 6:
            continue
        commit_hash, author_name, author_email, committer_name, committer_email, subject = parts
        if (
            author_name != URANIUM_GIT_NAME or author_email != URANIUM_GIT_EMAIL
            or committer_name != URANIUM_GIT_NAME or committer_email != URANIUM_GIT_EMAIL
        ):
            continue
        if commit_has_valid_note(commit_hash, repo_dir):
            return commit_hash
    return None


def worktree_is_tampered(repo_dir: Path | None = None) -> bool:
    repo_dir = repo_dir or URANIUM_DIR
    if not repo_has_head(repo_dir):
        return False
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        return True
    return not head_is_uranium_commit(repo_dir)


def restore_last_verifiable_commit(repo_dir: Path | None = None) -> None:
    repo_dir = repo_dir or URANIUM_DIR
    target = latest_verifiable_commit(repo_dir)
    if target is None:
        subprocess.run(["git", "checkout", "--orphan", "uranium-trusted"], cwd=repo_dir, check=False, capture_output=True)
        subprocess.run(["git", "rm", "-rf", "--cached", "."], cwd=repo_dir, check=False, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=repo_dir, check=False, capture_output=True)
        reset_git_identity_to_unauthorized(repo_dir)
        return
    subprocess.run(["git", "reset", "--hard", target], cwd=repo_dir, check=False, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_dir, check=False, capture_output=True)
    reset_git_identity_to_unauthorized(repo_dir)

match platform.system():
    case "Windows":
        URANIUM_DIR: Path = Path(os.environ["LOCALAPPDATA"]) / "Uranium"
    case "Darwin":
        URANIUM_DIR: Path = Path.home() / "Library" / "Application Support" / "Uranium"
    case _:
        URANIUM_DIR: Path = Path(os.environ.get(
            "XDG_DATA_HOME",
            Path.home() / ".local" / "share"
        )) / "uranium"

class Chunk:
    @staticmethod
    def is_reserved_name(name: str) -> bool:
        return name in RESERVED_CHUNK_NAMES

    @staticmethod
    def is_chunk_info_key(key: str) -> bool:
        return key.strip() == "chunk-info"

    def __init__(self, name: str, create: bool = True) -> None:
        if self.is_reserved_name(name):
            raise ValueError(f"Chunk name '{name}' is reserved and cannot be used.")
        self.name: str = name
        self.path: Path = URANIUM_DIR / self.name
        if worktree_is_tampered(URANIUM_DIR):
            restore_last_verifiable_commit(URANIUM_DIR)
        if create and not self.path.exists():
            self.path.mkdir(parents=True)
            try:
                subprocess.run(["git", "init"], cwd=URANIUM_DIR, check=True, capture_output=True)
                reset_git_identity_to_unauthorized(URANIUM_DIR)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to initialize git repository: {e}")

    def _require_clean_worktree(self) -> None:
        if worktree_is_tampered(URANIUM_DIR):
            restore_last_verifiable_commit(URANIUM_DIR)

    def _commit(self, action: str, key: str) -> bool:
        machine = platform.node() or "uranium"
        message = f"{machine}: [{self.name}] {action}"
        if key:
            message += f" {key}"
        try:
            parse_commit_message(message)
        except ValueError:
            return False
        try:
            _ensure_git_identity()
            subprocess.run(["git", "add", "-A"], cwd=URANIUM_DIR, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", f"user.name={URANIUM_GIT_NAME}", "-c", f"user.email={URANIUM_GIT_EMAIL}", "commit", "--allow-empty", "-m", message],
                cwd=URANIUM_DIR,
                check=True,
                capture_output=True,
            )
            commit_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=URANIUM_DIR,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            commit_meta = subprocess.run(
                ["git", "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce%x00%s", "HEAD"],
                cwd=URANIUM_DIR,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip().split("\x00")
            if len(commit_meta) != 5:
                raise subprocess.CalledProcessError(1, ["git", "show"])
            author_name, author_email, committer_name, committer_email, subject = commit_meta
            note = _create_commit_note(
                machine,
                self.name,
                action,
                key,
                commit_hash=commit_hash,
                subject=subject,
                author_name=author_name,
                author_email=author_email,
                committer_name=committer_name,
                committer_email=committer_email,
            )
            subprocess.run(
                ["git", "notes", "--ref", URANIUM_NOTE_REF, "add", "-f", "-m", json.dumps(note, separators=(",", ":"))],
                cwd=URANIUM_DIR,
                check=True,
                capture_output=True,
            )
            if not head_is_uranium_commit(URANIUM_DIR):
                restore_last_verifiable_commit(URANIUM_DIR)
                return False
            reset_git_identity_to_unauthorized(URANIUM_DIR)
        except subprocess.CalledProcessError:
            reset_git_identity_to_unauthorized(URANIUM_DIR)
            return False
        return True
    def _key_to_path(self, key: str, no_exist: str) -> Path | any:
        path: Path = self.path
        for segment in key.split("."):
            path = path / segment.strip()
        path = Path(str(path) + ".json")
        if not path.exists():
            match no_exist:
                case "error":
                    raise FileNotFoundError(f"'{key}' does not exist.")
                case "none":
                    return None
                case "return":
                    return path
        else:
            return path
    def _resolve_target(self, key: str = "") -> Path | None:
        if not key:
            return self.path
        target = self.path
        parts = [part.strip() for part in key.split(".") if part.strip()]
        for index, segment in enumerate(parts):
            directory = target / segment
            file_path = target / f"{segment}.json"
            if directory.exists() and directory.is_dir():
                target = directory
                continue
            if file_path.exists():
                if index == len(parts) - 1:
                    return target
                return None
            return None
        return target
    def ls(self, key: str = "") -> list[str]:
        self._require_clean_worktree()
        target = self._resolve_target(key)
        if target is None or not target.exists():
            return []
        return sorted(item.name.removesuffix(".json") for item in target.iterdir())
    def tree(self, key: str = "") -> str:
        self._require_clean_worktree()
        root = self._resolve_target(key)
        if root is None or not root.exists():
            return ""
        lines: list[str] = [root.name if root != self.path else self.name]
        def walk(directory: Path, prefix: str = "") -> None:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
            for index, entry in enumerate(entries):
                connector = "└── " if index == len(entries) - 1 else "├── "
                label = entry.name.removesuffix(".json") if entry.is_file() else entry.name
                lines.append(f"{prefix}{connector}{label}")
                if entry.is_dir():
                    child_prefix = prefix + ("    " if index == len(entries) - 1 else "│   ")
                    walk(entry, child_prefix)
        walk(root)
        return "\n".join(lines)
    def _get_chunk_info(self) -> str | None:
        self._require_clean_worktree()
        info_path = self._key_to_path("chunk-info", no_exist="none")
        if info_path is None or not info_path.exists():
            return None
        with info_path.open() as file:
            value = json.load(file)
        return value if isinstance(value, str) else str(value)
    def get(self, key: str, default: any | ... = ...) -> any:
        self._require_clean_worktree()
        path_or_return: Path | any = self._key_to_path(key, no_exist="error" if default is ... else "none")
        if not path_or_return:
            return default
        with path_or_return.open() as file:
            return json.load(file)
    def __getitem__(self, key: str) -> any:
        return self.get(key, ...)
    def set(self, key: str, value: any) -> bool:
        self._require_clean_worktree()
        if self.is_chunk_info_key(key):
            path: Path = self._key_to_path(key, no_exist="return")
            if path.exists():
                return False
        path: Path = self._key_to_path(key, no_exist="return")
        if not path.parent.exists():
            path.parent.mkdir(parents=True)
        with path.open("w") as file:
            json.dump(value, file)
        return self._commit("set", key)
    def __setitem__(self, key: str, value: any) -> None:
        self.set(key, value)
    def data(self, key: str, default: any | ... = ...) -> any:
        self._require_clean_worktree()
        if self.is_chunk_info_key(key):
            info = self.get_chunk_info()
            if info is not None:
                return info
        path_or_return: Path | any = self._key_to_path(key, no_exist="error" if default is ... else "none")
        if path_or_return is None:
            path = self._key_to_path(key, no_exist="return")
            if path is None:
                return default
            if not path.parent.exists():
                path.parent.mkdir(parents=True)
            with path.open("w") as file:
                json.dump(default, file)
            self._commit("data", key)
            return default
        return self.get(key, default)
    def rm(self, key: str) -> bool:
        self._require_clean_worktree()
        if self.is_chunk_info_key(key):
            return False
        path_or_return: Path | any = self._key_to_path(key, no_exist="none")
        if path_or_return is None or not path_or_return.exists():
            return False
        path_or_return.unlink()
        return self._commit("rm", key)
    def __delitem__(self, key: str) -> None:
        self.rm(key)
    def rmchunk(self) -> bool:
        self._require_clean_worktree()
        if self.is_reserved_name(self.name):
            return False
        if not self.path.exists():
            return False
        shutil.rmtree(self.path)
        self._commit("rmchunk", self.name)
        return not self.path.exists()