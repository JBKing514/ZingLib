"""Isolated HTTP upload and metadata regressions; no real database writes."""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

_runtime = tempfile.TemporaryDirectory()
os.environ['DATA_UI_RUNTIME_DIR'] = _runtime.name
os.environ['DATA_UI_LOCAL_LIB_DIR'] = str(Path(_runtime.name) / 'library')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from webapi.routers import local_lib
from webapi.services import local_lib_service as lib
from webapi.services import tag_reapply_service as tags


class UploadRegression(unittest.TestCase):
    def setUp(self):
        lib.LOCAL_LIB_DIR.mkdir(parents=True, exist_ok=True)
        app = FastAPI()
        app.include_router(local_lib.router)
        self.client = TestClient(app)

    def test_1201_files_keep_name_and_commit(self):
        batch = ''
        for start in range(0, 1201, 200):
            files = [('files', (f'{i}.jpg', b'image', 'image/jpeg')) for i in range(start, min(start + 200, 1201))]
            paths = [f'Collection/Named Gallery/{i}.jpg' for i in range(start, min(start + 200, 1201))]
            res = self.client.post('/api/local-lib/upload-folder', files=files,
                data={'folder_name': 'Collection', 'batch_id': batch, 'inspect': 'false', 'relative_paths': paths})
            self.assertEqual(res.status_code, 200, res.text)
            batch = res.json()['batch_id']
        report = self.client.get('/api/local-lib/upload/staged', params={'batch_id': batch}).json()
        self.assertEqual(report['galleries'][0]['name'], 'Named Gallery')
        self.assertEqual(report['galleries'][0]['page_count'], 1201)
        with patch.object(local_lib, 'scan_local_lib', return_value={'ok': True}) as scan:
            res = self.client.post('/api/local-lib/upload/commit', json={
                'batch_id': batch, 'path': 'Collection/Named Gallery', 'name': 'Named Gallery'})
            self.assertEqual(res.status_code, 200, res.text)
            scan.assert_called_once_with(path_hint='Named Gallery')
        self.assertEqual(len(list((lib.LOCAL_LIB_DIR / 'Named Gallery').glob('*.jpg'))), 1201)
        self.assertEqual(self.client.post('/api/local-lib/upload/discard', json={'batch_id': batch}).status_code, 200)

    def test_single_folder_name_and_unknown_batch(self):
        res = self.client.post('/api/local-lib/upload-folder', files={'files': ('1.jpg', b'image')},
            data={'folder_name': 'Real Name', 'relative_paths': 'Real Name/1.jpg'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['galleries'][0]['name'], 'Real Name')
        res = self.client.post('/api/local-lib/upload-folder', files={'files': ('1.jpg', b'image')},
            data={'folder_name': 'Real Name', 'batch_id': 'abc123'})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()['detail'], 'staged batch not found')

    def test_main_router_does_not_fall_through_to_spa(self):
        from webapi.main import app
        # Exercise real registration order without auth or startup/DB effects.
        isolated = FastAPI()
        isolated.include_router(app.router)
        client = TestClient(isolated)
        res = client.get('/api/local-lib/upload/staged', params={'batch_id': '../bad'})
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()['detail'], 'invalid staging id')

    def test_archive_scans_file_path(self):
        archive = lib.LOCAL_LIB_DIR / 'Book.cbz'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('001.jpg', b'image')
        with patch.object(lib, 'query_rows', return_value=[]), patch.object(lib, 'enrich_local_work_metadata', return_value={'ok': True}):
            result = lib.scan_local_lib('Book.cbz')
        self.assertEqual(result['upserts'], 1)

    def test_archive_commit_keeps_its_extension(self):
        """Committing an archive must not strip its extension.

        The review dialog shows an archive's display name without the suffix
        ("Solo", not "Solo.zip") and the panel sends that as `name`. If the
        commit renamed the file to `Solo`, the scanner would stop recognising it
        as an archive and the ingest would fail with a 500.
        """
        target = lib.LOCAL_LIB_DIR / 'Uploads'
        target.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('001.jpg', b'image')
        res = self.client.post('/api/local-lib/upload-folder',
            files={'files': ('Solo.zip', buf.getvalue(), 'application/zip')},
            data={'folder_name': 'BoxZip', 'relative_paths': ['BoxZip/Solo.zip'], 'inspect': 'false'})
        self.assertEqual(res.status_code, 200, res.text)
        batch = res.json()['batch_id']
        with patch.object(local_lib, 'scan_local_lib', return_value={'ok': True}) as scan:
            res = self.client.post('/api/local-lib/upload/commit', json={
                'batch_id': batch, 'path': 'BoxZip/Solo.zip', 'name': 'Solo',
                'kind': 'archive', 'target_path': 'Uploads'})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertTrue(res.json()['name'].endswith('.zip'), res.json()['name'])
            self.assertTrue((target / 'Solo.zip').is_file(),
                            sorted(p.name for p in target.iterdir()))
            scan.assert_called_once_with(path_hint='Uploads/Solo.zip')
        self.client.post('/api/local-lib/upload/discard', json={'batch_id': batch})

    def test_translation_and_user_metadata(self):
        ns, mapping = lib._build_translation_maps({'data': [
            {'namespace': 'rows', 'data': {'artist': {'name': 'Creator'}}},
            {'namespace': 'artist', 'data': {'example': {'name': 'Example Author'}}},
        ]})
        self.assertEqual(lib._translate_tag('artist:example', ns, mapping), 'Creator:Example Author')
        self.assertEqual(lib._translate_tag('custom:unlisted', ns, mapping), 'custom:unlisted')
        row = {'raw': {'tags_raw': ['artist:example'], 'eh_raw': {'category': 'manga'},
            'user_meta': {'title': 'Edited'}, 'bookmark': {'page': 3}}}
        result = tags.plan_reapply_row(row, 'translated', ns, mapping, current_sig='test', force=True)
        self.assertIn('Creator:Example Author', result['tags'])
        self.assertIn('category:manga', result['tags'])
        self.assertNotIn('user_meta', result['raw_patch'])
        self.assertNotIn('bookmark', result['raw_patch'])


if __name__ == '__main__':
    unittest.main()
