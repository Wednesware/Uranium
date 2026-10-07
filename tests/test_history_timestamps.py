import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uranium
from uranium import parse_commit_message, worktree_is_tampered
from uranium.cli import _format_history_timestamp


class HistoryTimestampTests(unittest.TestCase):
    def test_recent_timestamp_uses_clock_time(self):
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2024, 6, 10, 12, 0, 0, tzinfo=local_tz)
        recent = datetime(2024, 6, 10, 5, 30, 45, tzinfo=local_tz)

        self.assertEqual(_format_history_timestamp(recent.isoformat(), now=now), "05:30:45")

    def test_older_timestamp_uses_date(self):
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2024, 6, 10, 12, 0, 0, tzinfo=local_tz)
        older = now - timedelta(days=1, minutes=1)

        self.assertEqual(_format_history_timestamp(older.isoformat(), now=now), "2024-06-09")

    def test_parse_commit_message_extracts_machine_chunk_and_action(self):
        self.assertEqual(
            parse_commit_message("archmercury: [Loginator] set user.displayname"),
            {
                "machine": "archmercury",
                "chunk": "Loginator",
                "operation": "set",
                "key": "user.displayname",
            },
        )

    def test_parse_commit_message_rejects_non_uranium_actions(self):
        with self.assertRaises(ValueError):
            parse_commit_message("archmercury: [Loginator] malicious update")

    def test_head_commit_with_invalid_action_is_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            (repo / "values.txt").write_text("ping\n", encoding="utf-8")
            subprocess.run(["git", "add", "values.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "archmercury: [Loginator] malicious update"], cwd=repo, check=True, capture_output=True)

            self.assertFalse(uranium.head_is_uranium_commit(repo))
            self.assertTrue(uranium.worktree_is_tampered(repo))

    def test_action_mismatch_is_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            (repo / "Loginator").mkdir()
            (repo / "Loginator" / "user.json").write_text('{"displayname": "Alice"}\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "archmercury: [Loginator] rm user.displayname"], cwd=repo, check=True, capture_output=True)
            commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            note = {
                "version": 1,
                "machine": "archmercury",
                "chunk": "Loginator",
                "operation": "rm",
                "key": "user.displayname",
                "commit": commit_hash,
                "subject": "archmercury: [Loginator] rm user.displayname",
                "author_name": "Uranium",
                "author_email": "uranium@localhost",
                "committer_name": "Uranium",
                "committer_email": "uranium@localhost",
            }
            subprocess.run(["git", "notes", "--ref", "uranium", "add", "-f", "-m", json.dumps(note, separators=(",", ":"))], cwd=repo, check=True, capture_output=True)

            self.assertFalse(uranium.head_is_uranium_commit(repo))
            self.assertTrue(uranium.worktree_is_tampered(repo))

    def test_non_uranium_commit_format_is_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            (repo / "values.txt").write_text("ping\n", encoding="utf-8")
            subprocess.run(["git", "add", "values.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            self.assertTrue(uranium.worktree_is_tampered(repo))

    def test_head_commit_without_note_is_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            (repo / "values.txt").write_text("ping\n", encoding="utf-8")
            subprocess.run(["git", "add", "values.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "archmercury: [Loginator] set user.displayname"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            self.assertTrue(uranium.worktree_is_tampered(repo))

    def test_head_commit_with_wrong_note_is_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            (repo / "values.txt").write_text("ping\n", encoding="utf-8")
            subprocess.run(["git", "add", "values.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "archmercury: [Loginator] set user.displayname"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "notes", "--ref", "uranium", "add", "-f", "-m", '{"version":1,"machine":"evil","chunk":"Loginator","operation":"set","key":"user.displayname"}'],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            self.assertTrue(uranium.worktree_is_tampered(repo))

    def test_worktree_is_tampered_when_tracked_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            data_file = repo / "values.json"
            data_file.write_text('{"answer": 42}\n', encoding="utf-8")

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "add", "values.json"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            data_file.write_text('{"answer": 99}\n', encoding="utf-8")

            self.assertTrue(worktree_is_tampered(repo))

    def test_library_recovers_from_dirty_worktree(self):
        old_dir = uranium.URANIUM_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            chunk_dir = repo / "Loginator"
            chunk_dir.mkdir()
            data_file = chunk_dir / "user.json"
            data_file.write_text('{"displayname": "Alice"}\n', encoding="utf-8")

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Uranium"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "uranium@localhost"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "archmercury: [Loginator] set user.displayname"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            commit_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            note = {
                "version": 1,
                "machine": "archmercury",
                "chunk": "Loginator",
                "operation": "set",
                "key": "user.displayname",
                "commit": commit_hash,
                "subject": "archmercury: [Loginator] set user.displayname",
                "author_name": "Uranium",
                "author_email": "uranium@localhost",
                "committer_name": "Uranium",
                "committer_email": "uranium@localhost",
            }
            subprocess.run(
                ["git", "notes", "--ref", "uranium", "add", "-f", "-m", json.dumps(note, separators=(",", ":"))],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            uranium.URANIUM_DIR = repo
            try:
                data_file.write_text('{"displayname": "Mallory"}\n', encoding="utf-8")
                chunk = uranium.Chunk("Loginator", create=False)
                self.assertEqual(chunk.get("user"), {"displayname": "Alice"})
                self.assertFalse(uranium.worktree_is_tampered(repo))
            finally:
                uranium.URANIUM_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
