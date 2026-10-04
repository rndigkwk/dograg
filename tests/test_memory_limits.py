import os
import unittest
from unittest.mock import Mock, patch

from src import memory_limits


class MemoryLimitTests(unittest.TestCase):
    def test_sets_thread_limits_without_overriding_existing_values(self):
        with patch.dict(os.environ, {"MKL_NUM_THREADS": "4"}, clear=False), \
                patch.object(memory_limits, "_glibc", return_value=None):
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "TOKENIZERS_PARALLELISM"):
                os.environ.pop(name, None)
            memory_limits.limit_native_memory()
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "2")
            self.assertEqual(os.environ["MKL_NUM_THREADS"], "4")
            self.assertEqual(os.environ["TOKENIZERS_PARALLELISM"], "false")

    def test_caps_malloc_arenas_and_trims_on_glibc(self):
        libc = Mock()
        with patch.dict(os.environ, {}, clear=False), patch.object(memory_limits, "_glibc", return_value=libc):
            memory_limits.limit_native_memory(arenas=2)
            memory_limits.release_free_memory()
        libc.mallopt.assert_called_once_with(memory_limits.M_ARENA_MAX, 2)
        libc.malloc_trim.assert_called_once_with(0)

    def test_no_glibc_off_linux(self):
        with patch.object(memory_limits.sys, "platform", "win32"):
            self.assertIsNone(memory_limits._glibc())
            memory_limits.release_free_memory()  # must not raise


if __name__ == "__main__":
    unittest.main()
