import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import InMemoryRuntimeStore, SQLiteRuntimeStore  # noqa: E402
from tenta_runtime.storage import create_runtime_store, storage_url_from_options  # noqa: E402


class RuntimeStorageFactoryTests(unittest.TestCase):
    def test_memory_storage_url(self):
        store = create_runtime_store("memory")

        self.assertIsInstance(store, InMemoryRuntimeStore)

    def test_sqlite_storage_url_uses_requested_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "runtime.sqlite3"
            store = create_runtime_store(f"sqlite:{db_path}")

            self.assertIsInstance(store, SQLiteRuntimeStore)
            self.assertEqual(store.path, str(db_path))
            store.close()

    def test_storage_url_from_options_prefers_memory(self):
        self.assertEqual(
            storage_url_from_options(storage_url="sqlite:data/foo.sqlite3", memory_storage=True),
            "memory",
        )

    def test_storage_url_from_options_wraps_legacy_storage_path(self):
        self.assertEqual(
            storage_url_from_options(storage_path="data/custom.sqlite3"),
            "sqlite:data/custom.sqlite3",
        )


if __name__ == "__main__":
    unittest.main()
