import os
import json
import subprocess
import sys
import tempfile
import time
import unittest

try:
    from PySide6.QtCore import QCoreApplication
    from gui.single_instance import SingleInstance
    PYSIDE_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for local-socket tests")
class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _forward_process(self, scope, arguments, cwd):
        code = (
            "import json,sys; "
            "from PySide6.QtCore import QCoreApplication; "
            "from gui.single_instance import SingleInstance; "
            "app=QCoreApplication([]); instance=SingleInstance(scope=sys.argv[1]); "
            "ok=instance.forward(json.loads(sys.argv[2]),sys.argv[3]); "
            "sys.exit(0 if ok else 2)"
        )
        return subprocess.Popen(
            [sys.executable, "-c", code, scope, json.dumps(arguments), cwd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _pump_until_finished(self, process, timeout=6):
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, f"local instance message failed\n{stdout}\n{stderr}")
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.005)

    def test_second_instance_forwards_arguments_to_primary(self):
        with tempfile.TemporaryDirectory() as scope:
            primary = SingleInstance(scope=scope)
            try:
                self.assertTrue(primary.acquire())
                received = []
                primary.message_received.connect(received.append)
                primary.set_ready()
                process = self._forward_process(scope, ["example.oder"], os.getcwd())
                self._pump_until_finished(process)
                self.app.processEvents()
                self.assertEqual(received[0]["arguments"], ["example.oder"])
                self.assertEqual(received[0]["cwd"], os.getcwd())
            finally:
                primary.close()

    def test_messages_wait_until_primary_window_is_ready(self):
        with tempfile.TemporaryDirectory() as scope:
            primary = SingleInstance(scope=scope)
            try:
                self.assertTrue(primary.acquire())
                process = self._forward_process(scope, [], scope)
                self._pump_until_finished(process)
                pending = primary.set_ready()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["cwd"], scope)
            finally:
                primary.close()


if __name__ == "__main__":
    unittest.main()
