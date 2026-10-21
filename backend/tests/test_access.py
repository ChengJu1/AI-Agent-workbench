import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.application import create_app
from app.config import Settings
from app.container import build_services


class AccessTokenTests(unittest.TestCase):
    def client(self, **settings):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Settings(database_path=Path(folder.name) / 'a.db', backup_keep=0, **settings)
        client = TestClient(create_app(settings=config, services=build_services(config)))
        self.addCleanup(client.close)
        return client

    def test_no_token_keeps_the_local_api_open(self):
        client = self.client()
        self.assertEqual(client.get('/api/applications').status_code, 200)
        self.assertEqual(client.post('/api/session', json={'token': 'x'}).json(), {'required': False})

    def test_token_guards_the_api_by_header_or_session_cookie(self):
        client = self.client(access_token='s3cret-token')
        self.assertEqual(client.get('/api/health').status_code, 200)  # Health checks stay open.
        refused = client.get('/api/applications')
        self.assertEqual((refused.status_code, refused.json()['error_code']), (401, 'AUTH_REQUIRED'))
        self.assertEqual(client.get('/api/applications', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(client.get('/api/applications', headers={'Authorization': 'Bearer s3cret-token'}).status_code, 200)
        self.assertEqual(client.post('/api/session', json={'token': 'nope'}).status_code, 401)
        opened = client.post('/api/session', json={'token': 's3cret-token'})
        self.assertIn('httponly', opened.headers['set-cookie'].lower())
        self.assertEqual(client.get('/api/applications/calendar.ics').status_code, 200)  # Plain links ride on the cookie.
        client.delete('/api/session')
        self.assertEqual(client.get('/api/applications').status_code, 401)

    def test_refuses_to_serve_other_machines_without_a_token(self):
        with self.assertRaises(RuntimeError):
            create_app(settings=Settings(trusted_hosts=('localhost', '192.168.1.20'), backup_keep=0))
        create_app(settings=Settings(trusted_hosts=('localhost', '192.168.1.20'), access_token='t', backup_keep=0))


if __name__ == '__main__':
    unittest.main()
