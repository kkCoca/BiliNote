import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _reset_app_modules() -> None:
    for k in list(sys.modules.keys()):
        if k == 'app' or k.startswith('app.'):
            sys.modules.pop(k, None)


class TestBatchManager(unittest.TestCase):
    def test_create_register_and_refresh(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            mgr = BatchManager(output_dir=td)
            batch_id = mgr.create_batch(['u1', 'u2'])
            mgr.register_task(batch_id, 't1', 'u1')
            mgr.register_task(batch_id, 't2', 'u2')

            # t1 succeed, t2 failed
            with open(f'{td}/t1.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'SUCCESS', 'message': ''}, f)
            with open(f'{td}/t2.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'FAILED', 'message': 'boom'}, f)

            data = mgr.refresh_from_task_status(batch_id)
            self.assertEqual(data['completed'], 1)
            self.assertEqual(data['failed'], 1)
            self.assertEqual(data['tasks']['t2']['error'], 'boom')


if __name__ == '__main__':
    unittest.main()
