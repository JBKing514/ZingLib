import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

_temp = tempfile.TemporaryDirectory()
os.environ['DATA_UI_RUNTIME_DIR'] = _temp.name
os.environ['DATA_UI_LOCAL_LIB_DIR'] = str(Path(_temp.name) / 'library')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from webapi.routers import reader, local_lib, media
from webapi.services import local_lib_service as lib, auth_service


class ReaderArchiveRegression(unittest.TestCase):
    def test_archive_manifest_image_and_session(self):
        lib.LOCAL_LIB_DIR.mkdir(parents=True, exist_ok=True)
        image = io.BytesIO()
        Image.new('RGB', (32, 48), 'green').save(image, 'PNG')
        for suffix in ('.zip', '.cbz'):
            name = 'Book' + suffix
            with zipfile.ZipFile(lib.LOCAL_LIB_DIR / name, 'w') as z:
                z.writestr('chapter/10.png', image.getvalue())
                z.writestr('chapter/2.png', image.getvalue())
                z.writestr('__MACOSX/._2.png', b'ignored')
            row = {'source': 'local', 'local_dir': name, 'title': 'Book'}
            app = FastAPI()
            app.include_router(reader.router)
            app.include_router(media.router)
            with patch.object(lib, 'query_rows', return_value=[row]), patch.object(reader, 'query_rows', return_value=[row]), patch.object(reader, 'resolve_config', return_value=({}, {})), patch.object(media, 'resolve_config', return_value=({}, {})):
                with TestClient(app) as client:
                    key = 'archive-test-' + suffix[1:]
                    res = client.get(f'/api/reader/{key}/manifest')
                    self.assertEqual(res.json()['page_count'], 2)
                    self.assertEqual(lib.list_local_gallery_pages(name)[0], 'chapter/2.png')
                    page = client.get(f'/api/reader/{key}/page/1?mode=high')
                    self.assertEqual(page.status_code, 200, page.text if page.status_code != 200 else '')
                    self.assertEqual(Image.open(io.BytesIO(page.content)).size, (32, 48))
                    self.assertEqual(client.get(f'/api/thumb/work/{key}').status_code, 200)
                    session = client.post(f'/api/reader/{key}/session?page=1&ahead=1')
                    self.assertEqual(session.status_code, 200, session.text)
                    client.delete('/api/reader/session/' + session.json()['session_id'])

    def test_rebuild_requires_admin_password_and_confirmation(self):
        app = FastAPI()
        identity = {'uid': 'test', 'username': 'admin', 'role': 'admin'}
        @app.middleware('http')
        async def test_identity(request, call_next):
            request.state.auth_user = dict(identity)
            return await call_next(request)
        app.include_router(local_lib.router)
        sentinel = Path(_temp.name) / 'keep.txt'
        sentinel.write_text('keep')
        with TestClient(app) as client, patch.object(auth_service, 'authenticate_user', return_value=dict(identity)) as verify, patch.object(auth_service, 'auth_pepper', return_value=''), patch('webapi.services.db_service.db_dsn', return_value=''), patch.object(local_lib, 'query_rows', return_value=[{'removed': 3}]) as query:
            url = '/api/local-lib/rebuild-database'
            self.assertEqual(client.post(url, json={'password':'test'}).status_code, 400)
            identity['role'] = 'user'
            self.assertEqual(client.post(url, json={'confirm':True,'password':'test'}).status_code, 403)
            identity['role'] = 'admin'
            verify.return_value = None
            self.assertEqual(client.post(url, json={'confirm':True,'password':'bad'}).status_code, 403)
            query.assert_not_called()
            verify.return_value = dict(identity)
            result = client.post(url, json={'confirm':True,'password':'test'})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['removed'], 3)
            self.assertEqual(sentinel.read_text(), 'keep')
            self.assertIn('DELETE FROM works', query.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
