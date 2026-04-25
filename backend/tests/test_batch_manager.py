import json
import os
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

    def test_list_batches_returns_course_summaries(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            batch_id = 'batch-1'
            data = {
                'batch_id': batch_id,
                'title': 'Course title',
                'source_url': 'https://example.com/course',
                'cover_url': 'thumb1',
                'total': 2,
                'completed': 1,
                'failed': 0,
                'tasks': {
                    't1': {'video_url': 'u1', 'status': 'SUCCESS'},
                    't2': {'video_url': 'u2', 'status': 'PENDING'},
                },
                'created_at': '2026-04-25T00:00:00+00:00',
                'updated_at': '2026-04-25T00:01:00+00:00',
            }
            with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                json.dump(data, f)

            summaries = BatchManager(output_dir=td).list_batches()

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]['batch_id'], batch_id)
            self.assertEqual(summaries[0]['title'], 'Course title')
            self.assertEqual(summaries[0]['source_url'], 'https://example.com/course')
            self.assertEqual(summaries[0]['cover_url'], 'thumb1')
            self.assertEqual(summaries[0]['total'], 2)
            self.assertEqual(summaries[0]['completed'], 1)
            self.assertEqual(summaries[0]['failed'], 0)
            self.assertEqual(summaries[0]['running'], 1)
            self.assertEqual(summaries[0]['status'], 'RUNNING')
            self.assertEqual(summaries[0]['created_at'], '2026-04-25T00:00:00+00:00')
            self.assertTrue(summaries[0]['updated_at'])

    def test_list_batches_refreshes_child_status_files(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            batch_id = 'batch-1'
            data = {
                'batch_id': batch_id,
                'title': 'Course title',
                'source_url': 'https://example.com/course',
                'cover_url': 'thumb1',
                'total': 2,
                'completed': 0,
                'failed': 0,
                'tasks': {
                    't1': {'video_url': 'u1', 'status': 'PENDING', 'error': ''},
                    't2': {'video_url': 'u2', 'status': 'PENDING', 'error': ''},
                },
                'created_at': '2026-04-25T00:00:00+00:00',
                'updated_at': '2026-04-25T00:01:00+00:00',
            }
            with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                json.dump(data, f)
            with open(f'{td}/t1.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'SUCCESS', 'message': ''}, f)
            with open(f'{td}/t2.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'FAILED', 'message': 'boom'}, f)

            summaries = BatchManager(output_dir=td).list_batches()

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]['completed'], 1)
            self.assertEqual(summaries[0]['failed'], 1)
            self.assertEqual(summaries[0]['running'], 0)
            self.assertEqual(summaries[0]['status'], 'FAILED')

            with open(f'{td}/batch_{batch_id}.json', 'r', encoding='utf-8') as f:
                persisted = json.load(f)
            self.assertEqual(persisted['tasks']['t1']['status'], 'SUCCESS')
            self.assertEqual(persisted['tasks']['t2']['status'], 'FAILED')
            self.assertEqual(persisted['tasks']['t2']['error'], 'boom')

    def test_register_task_preserves_playlist_order_in_course_view(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            mgr = BatchManager(output_dir=td)
            batch_id = mgr.create_batch(['u1', 'u2', 'u3'])
            mgr.register_task(batch_id, 'task-z', 'u1')
            mgr.register_task(batch_id, 'task-a', 'u2')
            mgr.register_task(batch_id, 'task-m', 'u3')

            course_view = mgr.build_course_view(batch_id)

            self.assertEqual(
                [item['task_id'] for item in course_view['items']],
                ['task-z', 'task-a', 'task-m'],
            )
            self.assertEqual(
                [item['order'] for item in course_view['items']],
                [0, 1, 2],
            )

    def test_delete_task_from_batch_rejects_running_child_task(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'test.db')
            original_database_url = os.environ.get('DATABASE_URL')
            try:
                os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
                _reset_app_modules()

                from app.db.engine import Base, engine
                from app.db.models.video_tasks import VideoTask
                from app.services.batch_manager import BatchManager

                Base.metadata.create_all(bind=engine)
                batch_id = 'batch-running-child'
                data = {
                    'batch_id': batch_id,
                    'total': 2,
                    'completed': 1,
                    'failed': 0,
                    'tasks': {
                        't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'SUCCESS'},
                        't2': {'video_id': 'v2', 'video_url': 'u2', 'status': 'PENDING'},
                    },
                    'created_at': '2026-04-25T00:00:00+00:00',
                    'updated_at': '2026-04-25T00:01:00+00:00',
                }
                with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                with open(f'{td}/t2.json', 'w', encoding='utf-8') as f:
                    f.write('t2')

                with self.assertRaisesRegex(ValueError, '任务进行中'):
                    BatchManager(output_dir=td).delete_task_from_batch(batch_id, 't2')
            finally:
                if original_database_url is None:
                    os.environ.pop('DATABASE_URL', None)
                else:
                    os.environ['DATABASE_URL'] = original_database_url
                _reset_app_modules()

            with open(f'{td}/batch_{batch_id}.json', 'r', encoding='utf-8') as f:
                persisted = json.load(f)
            self.assertIn('t2', persisted['tasks'])
            self.assertTrue(os.path.exists(f'{td}/t2.json'))

    def test_delete_task_from_batch_rejects_success_without_result_file(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            batch_id = 'batch-success-not-settled'
            data = {
                'batch_id': batch_id,
                'total': 1,
                'completed': 1,
                'failed': 0,
                'tasks': {
                    't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'SUCCESS'},
                },
                'created_at': '2026-04-25T00:00:00+00:00',
                'updated_at': '2026-04-25T00:01:00+00:00',
            }
            with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                json.dump(data, f)
            with open(f'{td}/t1.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'SUCCESS', 'message': ''}, f)

            with self.assertRaisesRegex(ValueError, '任务进行中'):
                BatchManager(output_dir=td).delete_task_from_batch(batch_id, 't1')

            with open(f'{td}/batch_{batch_id}.json', 'r', encoding='utf-8') as f:
                persisted = json.load(f)
            self.assertIn('t1', persisted['tasks'])
            self.assertTrue(os.path.exists(f'{td}/t1.status.json'))

    def test_delete_task_from_batch_allows_failed_without_result_file(self):
        original_database_url = os.environ.get('DATABASE_URL')
        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = os.path.join(td, 'test.db')
                os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
                _reset_app_modules()

                from app.db.engine import Base, engine
                from app.db.models.video_tasks import VideoTask
                from app.services.batch_manager import BatchManager

                Base.metadata.create_all(bind=engine)
                batch_id = 'batch-failed-no-result'
                data = {
                    'batch_id': batch_id,
                    'total': 1,
                    'completed': 0,
                    'failed': 1,
                    'tasks': {
                        't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'FAILED'},
                    },
                    'created_at': '2026-04-25T00:00:00+00:00',
                    'updated_at': '2026-04-25T00:01:00+00:00',
                }
                with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                with open(f'{td}/t1.status.json', 'w', encoding='utf-8') as f:
                    json.dump({'status': 'FAILED', 'message': 'boom'}, f)

                result = BatchManager(output_dir=td).delete_task_from_batch(batch_id, 't1')

                self.assertNotIn('t1', result['tasks'])
                self.assertEqual(result['total'], 0)
                self.assertFalse(os.path.exists(f'{td}/t1.status.json'))
        finally:
            if original_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = original_database_url
            _reset_app_modules()

    def test_delete_task_from_batch_removes_child_and_updates_stats(self):
        original_database_url = os.environ.get('DATABASE_URL')
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = os.path.join(td, 'test.db')
                os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
                os.environ['NOTE_OUTPUT_DIR'] = td
                _reset_app_modules()

                from app.db.engine import Base, SessionLocal, engine
                from app.db.models.video_tasks import VideoTask
                from app.services.batch_manager import BatchManager

                Base.metadata.create_all(bind=engine)
                db = SessionLocal()
                db.add(VideoTask(video_id='v1', platform='bilibili', task_id='t1'))
                db.add(VideoTask(video_id='v2', platform='bilibili', task_id='t2'))
                db.commit()
                db.close()

                batch_id = 'batch-1'
                data = {
                    'batch_id': batch_id,
                    'total': 2,
                    'completed': 2,
                    'failed': 0,
                    'tasks': {
                        't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'SUCCESS'},
                        't2': {'video_id': 'v2', 'video_url': 'u2', 'status': 'SUCCESS'},
                    },
                    'created_at': '2026-04-25T00:00:00+00:00',
                    'updated_at': '2026-04-25T00:01:00+00:00',
                }
                with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                for suffix in ('.json', '.status.json', '_audio.json', '_transcript.json', '_markdown.md', '_markdown.status.json'):
                    with open(f'{td}/t1{suffix}', 'w', encoding='utf-8') as f:
                        f.write('t1')
                    with open(f'{td}/t2{suffix}', 'w', encoding='utf-8') as f:
                        f.write('t2')

                result = BatchManager(output_dir=td).delete_task_from_batch(batch_id, 't1')

                self.assertNotIn('t1', result['tasks'])
                self.assertIn('t2', result['tasks'])
                self.assertEqual(result['total'], 1)
                self.assertEqual(result['completed'], 1)
                self.assertEqual(result['failed'], 0)
                for suffix in ('.json', '.status.json', '_audio.json', '_transcript.json', '_markdown.md', '_markdown.status.json'):
                    self.assertFalse(os.path.exists(f'{td}/t1{suffix}'))
                    self.assertTrue(os.path.exists(f'{td}/t2{suffix}'))

                db = SessionLocal()
                self.assertIsNone(db.query(VideoTask).filter_by(task_id='t1').first())
                self.assertIsNotNone(db.query(VideoTask).filter_by(task_id='t2').first())
                db.close()
        finally:
            if original_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = original_database_url
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()
    def test_delete_batch_removes_terminal_batch_and_artifacts(self):
        original_database_url = os.environ.get('DATABASE_URL')
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = os.path.join(td, 'test.db')
                os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
                os.environ['NOTE_OUTPUT_DIR'] = td
                _reset_app_modules()

                from app.db.engine import Base, SessionLocal, engine
                from app.db.models.video_tasks import VideoTask
                from app.services.batch_manager import BatchManager

                Base.metadata.create_all(bind=engine)
                db = SessionLocal()
                db.add(VideoTask(video_id='v1', platform='bilibili', task_id='t1'))
                db.add(VideoTask(video_id='v2', platform='bilibili', task_id='t2'))
                db.commit()
                db.close()

                batch_id = 'batch-delete-all'
                data = {
                    'batch_id': batch_id,
                    'total': 2,
                    'completed': 1,
                    'failed': 1,
                    'tasks': {
                        't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'SUCCESS', 'order': 0},
                        't2': {'video_id': 'v2', 'video_url': 'u2', 'status': 'FAILED', 'order': 1},
                    },
                    'created_at': '2026-04-25T00:00:00+00:00',
                    'updated_at': '2026-04-25T00:01:00+00:00',
                }
                with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                for task_id, status in (('t1', 'SUCCESS'), ('t2', 'FAILED')):
                    with open(f'{td}/{task_id}.status.json', 'w', encoding='utf-8') as f:
                        json.dump({'status': status, 'message': ''}, f)
                    for suffix in ('.json', '_audio.json', '_transcript.json', '_markdown.md'):
                        with open(f'{td}/{task_id}{suffix}', 'w', encoding='utf-8') as f:
                            f.write(task_id)

                result = BatchManager(output_dir=td).delete_batch(batch_id)

                self.assertEqual(result['batch_id'], batch_id)
                self.assertEqual(result['deleted_task_ids'], ['t1', 't2'])
                self.assertFalse(os.path.exists(f'{td}/batch_{batch_id}.json'))
                for task_id in ('t1', 't2'):
                    for suffix in ('.json', '.status.json', '_audio.json', '_transcript.json', '_markdown.md', '_markdown.status.json'):
                        self.assertFalse(os.path.exists(f'{td}/{task_id}{suffix}'))

                db = SessionLocal()
                self.assertIsNone(db.query(VideoTask).filter_by(task_id='t1').first())
                self.assertIsNone(db.query(VideoTask).filter_by(task_id='t2').first())
                db.close()
        finally:
            if original_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = original_database_url
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()

    def test_delete_batch_rejects_running_batch(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            batch_id = 'batch-running'
            data = {
                'batch_id': batch_id,
                'total': 1,
                'completed': 0,
                'failed': 0,
                'tasks': {
                    't1': {'video_id': 'v1', 'video_url': 'u1', 'status': 'PENDING'},
                },
                'created_at': '2026-04-25T00:00:00+00:00',
                'updated_at': '2026-04-25T00:01:00+00:00',
            }
            with open(f'{td}/batch_{batch_id}.json', 'w', encoding='utf-8') as f:
                json.dump(data, f)
            with open(f'{td}/t1.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'PENDING', 'message': ''}, f)

            with self.assertRaisesRegex(ValueError, '合集仍有任务进行中'):
                BatchManager(output_dir=td).delete_batch(batch_id)

            self.assertTrue(os.path.exists(f'{td}/batch_{batch_id}.json'))
            self.assertTrue(os.path.exists(f'{td}/t1.status.json'))

    def test_delete_batch_missing_batch_raises_file_not_found(self):
        _reset_app_modules()
        from app.services.batch_manager import BatchManager

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                BatchManager(output_dir=td).delete_batch('missing')


if __name__ == '__main__':
    unittest.main()
