from pathlib import Path
import os
import subprocess
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import create_app, load_settings
from backend.cesium_credentials import CesiumCredentialStore, CredentialError, credential_path


TOKEN = 'sample.account.signature'
HEADERS = {'X-GCS-Token-Request': '1'}


@pytest.fixture
def saved_store(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows DPAPI test')
    return CesiumCredentialStore(tmp_path / 'user-data' / 'cesium-token.dat')


def test_read_only_missing_status_creates_nothing(saved_store):
    assert saved_store.status()['state'] == 'missing'
    assert saved_store.read() is None
    assert not saved_store.path.parent.exists()


def test_encrypted_token_survives_another_process_and_working_directory(saved_store, tmp_path):
    saved_store.save(TOKEN)
    assert TOKEN.encode() not in saved_store.path.read_bytes()
    source = str(Path(__file__).resolve().parents[1])
    script = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
              'from backend.cesium_credentials import CesiumCredentialStore; '
              'assert CesiumCredentialStore(Path(sys.argv[2])).read() == sys.argv[3]')
    result = subprocess.run([sys.executable, '-c', script, source, str(saved_store.path), TOKEN],
                            cwd=tmp_path, capture_output=True)
    assert result.returncode == 0
    saved_store.clear()
    assert saved_store.read() is None


def test_path_uses_user_directory_not_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'profile'))
    before = credential_path()
    monkeypatch.chdir(tmp_path)
    assert credential_path() == before == tmp_path / 'profile' / 'GroundControlPanel' / 'cesium-token.dat'


def test_corrupt_store_and_failed_replacement(saved_store):
    saved_store.save(TOKEN)
    with pytest.raises(CredentialError):
        saved_store.save('invalid secret value')
    assert saved_store.read() == TOKEN
    saved_store.path.write_bytes(b'corrupt file')
    assert saved_store.status()['state'] == 'unreadable'
    with pytest.raises(CredentialError):
        saved_store.read()
    saved_store.save(TOKEN)
    assert saved_store.read() == TOKEN


def test_api_import_read_clear_and_no_secret_in_status_or_bootstrap(config_path, tmp_path, saved_store, monkeypatch):
    calls = []
    async def validate(token, origin=None):
        calls.append(token)
        if token != TOKEN:
            raise HTTPException(422, 'Token 无效')
    monkeypatch.setattr('backend.cesium_api.validate_terrain_token', validate)
    app = create_app(settings=load_settings(config_path), static_dir=tmp_path,
                     start_udp=False, cesium_credentials=saved_store)
    with TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 12345)) as client:
        assert client.get('/api/earth/cesium-token', headers=HEADERS).json()['state'] == 'missing'
        assert calls == []
        assert client.post('/api/earth/cesium-token/read', headers=HEADERS).json()['token'] is None
        result = client.put('/api/earth/cesium-token', headers=HEADERS, json={'token': '\ufeff'+TOKEN+'\n'})
        assert result.status_code == 200
        assert result.json()['configured']
        assert TOKEN not in result.text
        assert result.headers['cache-control'] == 'no-store'
        assert TOKEN not in client.get('/api/bootstrap').text
        assert TOKEN not in client.get('/api/earth/cesium-token', headers=HEADERS).text
        read = client.post('/api/earth/cesium-token/read', headers=HEADERS)
        assert read.json()['token'] == TOKEN
        assert read.headers['cache-control'] == 'no-store'
        invalid = client.put('/api/earth/cesium-token', headers=HEADERS, json={'token': 'wrong.account.signature'})
        assert invalid.status_code == 422
        assert saved_store.read() == TOKEN
        malformed = client.put('/api/earth/cesium-token', headers=HEADERS, json={'token': 'secret with whitespace'})
        assert malformed.status_code == 422
        assert 'secret with whitespace' not in malformed.text
        oversized = client.put('/api/earth/cesium-token', headers=HEADERS, content='x'*9000)
        assert oversized.status_code == 413
        assert client.post('/api/earth/cesium-token/read').status_code == 403
        assert client.post('/api/earth/cesium-token/read', headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/earth/cesium-token', headers={**HEADERS, 'Host': 'evil.example'}).status_code == 403
        assert client.delete('/api/earth/cesium-token', headers=HEADERS).json()['state'] == 'missing'
        assert saved_store.read() is None


def test_network_failure_preserves_existing_token(config_path, tmp_path, saved_store, monkeypatch):
    saved_store.save(TOKEN)
    async def fail(*_args):
        raise HTTPException(503, '网络暂时不可用')
    monkeypatch.setattr('backend.cesium_api.validate_terrain_token', fail)
    app = create_app(settings=load_settings(config_path), static_dir=tmp_path,
                     start_udp=False, cesium_credentials=saved_store)
    with TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 12345)) as client:
        assert client.put('/api/earth/cesium-token', headers=HEADERS, json={'token': 'another.account.signature'}).status_code == 503
    assert saved_store.read() == TOKEN
