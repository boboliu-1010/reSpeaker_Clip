"""Durability faults exercised through the DTLS writer used by the receiver."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from server.dtls_upload_store import UploadWriter
from server.resume_store import ResumeError, ResumeStore

BLOCK = 16 * 1024


class ResumeStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = ResumeStore(self.directory, threading.Lock())
        self.data = bytes(range(256)) * 150
        self.identity = {
            'device': 'fixture', 'session': '20261019070446', 'segment': 1,
            'size': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest(),
            'object_id': hashlib.sha256(b'fixture/20261019070446/1').hexdigest(),
        }
        self.writer = None
        self.addCleanup(self.close)
        self.reopen()

    def close(self):
        if self.writer is not None:
            self.writer.close()

    def reopen(self):
        self.close()
        self.store = ResumeStore(self.directory, threading.Lock())
        self.writer = UploadWriter(self.store, self.identity, now=0)
        return self.writer

    def path(self, suffix):
        return self.directory / (self.identity['object_id'] + suffix)

    def commit(self, offset):
        end = min(offset + BLOCK, len(self.data))
        for start in range(offset, end, 1024):
            self.writer.data(start, self.data[start:min(start + 1024, end)], now=.1)
        self.writer.maybe_commit(.1, force=True)

    def complete(self, offset=0):
        for start in range(offset, len(self.data), BLOCK):
            self.commit(start)
        self.assertTrue(self.writer.stored)
        self.assertEqual(self.path('.bin').read_bytes(), self.data)

    def test_complete_idempotent_and_lost_reply(self):
        self.assertEqual(self.writer.durable, 0)
        self.commit(0)  # Pretend the durable ACK was lost.
        self.assertEqual(self.path('.partial').stat().st_mode & 0o077, 0)
        self.writer.data(0, self.data[:1024], now=.1)
        self.assertEqual(self.writer.duplicates, 1)
        self.assertEqual(self.reopen().durable, BLOCK)
        self.complete(BLOCK)
        self.assertTrue(self.reopen().stored)
        self.writer.data(2 * BLOCK, self.data[2 * BLOCK:2 * BLOCK + 1024], now=.1)
        self.assertEqual(self.path('.bin').stat().st_mode & 0o077, 0)
        self.assertEqual(len(list(self.directory.iterdir())), 2)  # Object + identity.

    def test_reopen_partial_and_discard_unacknowledged_tail(self):
        self.commit(0)
        with self.path('.partial').open('ab') as output:
            output.write(b'uncommitted tail')
        self.assertEqual(self.reopen().durable, BLOCK)
        self.assertEqual(self.path('.partial').read_bytes(), self.data[:BLOCK])
        self.complete(BLOCK)

    def test_failure_between_data_and_checkpoint_does_not_ack_tail(self):
        self.commit(0)
        original = self.store._save

        def fail_checkpoint(path, state):
            if state['offset'] > BLOCK:
                raise OSError('simulated checkpoint publication failure')
            original(path, state)

        with patch.object(self.store, '_save', side_effect=fail_checkpoint):
            with self.assertRaises(OSError):
                self.commit(BLOCK)
        self.assertEqual(self.writer.durable, BLOCK)
        self.assertEqual(self.reopen().durable, BLOCK)
        self.assertEqual(self.path('.partial').stat().st_size, BLOCK)
        self.complete(BLOCK)

    def test_restart_finalizes_checkpointed_full_file(self):
        self.commit(0)
        self.commit(BLOCK)
        with patch.object(self.store, '_finish', side_effect=OSError('before rename')):
            with self.assertRaises(OSError):
                self.commit(2 * BLOCK)
        self.assertTrue(self.reopen().stored)
        self.assertEqual(self.path('.bin').read_bytes(), self.data)

    def test_reopen_syncs_checkpoint_after_failed_directory_sync(self):
        self.commit(0)
        original = self.store._save

        def fail_after_checkpoint_rename(path, state):
            with patch.object(self.store, '_sync_directory', side_effect=OSError('directory fsync')):
                original(path, state)

        with patch.object(self.store, '_save', side_effect=fail_after_checkpoint_rename):
            with self.assertRaises(OSError):
                self.commit(BLOCK)
        self.close()
        with patch.object(self.store, '_sync_directory', wraps=self.store._sync_directory) as sync:
            self.writer = UploadWriter(self.store, self.identity, now=0)
            self.assertEqual(self.writer.durable, 2 * BLOCK)
            sync.assert_called_once()

    def test_restart_after_final_rename_cleans_stale_checkpoint(self):
        self.commit(0)
        self.commit(BLOCK)
        original = self.store._sync_directory

        def fail_after_rename():
            if self.path('.bin').exists():
                raise OSError('after rename')
            original()

        with patch.object(self.store, '_sync_directory', side_effect=fail_after_rename):
            with self.assertRaises(OSError):
                self.commit(2 * BLOCK)
        self.assertTrue(self.reopen().stored)
        self.assertEqual(len(list(self.directory.iterdir())), 2)

    def test_wrong_offset_content_or_identity_never_advances_checkpoint(self):
        self.commit(0)
        for offset, data, expected in (
                (BLOCK + 1, b'gap', 400), (0, b'x' * 1024, 409)):
            with self.subTest(offset=offset):
                with self.assertRaises(ResumeError) as result:
                    self.writer.data(offset, data, now=.1)
                self.assertEqual(result.exception.code, expected)
                self.assertEqual(self.writer.durable, BLOCK)
        self.close()
        with self.assertRaises(ResumeError) as result:
            UploadWriter(self.store, dict(self.identity, sha256='0' * 64), now=0)
        self.assertEqual(result.exception.code, 409)
        self.assertEqual(self.reopen().durable, BLOCK)

    def test_corrupted_prefix_is_never_published_and_can_restart(self):
        self.commit(0)
        with self.path('.partial').open('r+b') as output:
            output.write(b'x')
        self.commit(BLOCK)
        with self.assertRaises(ResumeError) as result:
            self.commit(2 * BLOCK)
        self.assertEqual(result.exception.code, 422)
        self.assertFalse(self.path('.bin').exists())
        self.assertEqual(self.reopen().durable, 0)
        self.complete()

    def test_missing_data_or_bad_checkpoint_fails_without_guessing_offset(self):
        self.commit(0)
        self.close()
        self.path('.partial').write_bytes(b'short')
        with self.assertRaises(ResumeError) as result:
            self.reopen()
        self.assertEqual(result.exception.code, 500)
        self.path('.checkpoint').write_text(json.dumps({
            'version': 1, 'size': len(self.data), 'offset': True,
        }))
        with self.assertRaises(ResumeError) as result:
            self.reopen()
        self.assertEqual(result.exception.code, 500)

    def test_concurrent_objects_keep_independent_checkpoints(self):
        second = dict(self.identity, segment=2, object_id=hashlib.sha256(b'second').hexdigest())
        with ThreadPoolExecutor(max_workers=2) as pool:
            def upload(identity):
                writer = UploadWriter(self.store, identity, now=0)
                try:
                    for start in range(0, len(self.data), 1024):
                        writer.data(start, self.data[start:start + 1024], now=.1)
                    return writer.stored
                finally:
                    writer.close()
            self.close()
            self.assertEqual(list(pool.map(upload, [self.identity, second])), [True, True])
        self.assertTrue(self.reopen().stored)
        self.assertEqual((self.directory / (second['object_id'] + '.bin')).read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
