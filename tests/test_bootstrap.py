import base64
import json
import zlib
from server.bootstrap import prepare_storage, restore_backup
from server.db import db


def test_storage_and_migration_are_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('SQLITE_DB_PATH', str(tmp_path / 'data/movie.db'))
    prepare_storage()
    assert (tmp_path / 'data').is_dir()
    pid = 'prj_aaaabbbb'
    backup = {'version': 1, 'projects': [{'project': {'id': pid, 'title': '旧项目', 'source_text': '原始剧情', 'brief': {}, 'round_count': 2}, 'detail': {'messages': [{'role':'user', 'content':'原始剧情'}]}, 'questions': {'project_id':pid,'status':'collecting','round':2,'brief_completion':0,'questions':[],'assumptions':[],'can_confirm':False}}]}
    encoded = base64.b64encode(zlib.compress(json.dumps(backup).encode())).decode()
    monkeypatch.setenv('PROJECT_MIGRATION_B64', encoded)
    restore_backup()
    assert db.get_project(pid)['title'] == '旧项目'
    assert db.get_project(pid)['round_count'] == 2
    assert len(db.get_messages(pid)) == 1
    db.update_project_brief(pid, {}, title='用户新标题')
    monkeypatch.setenv('PROJECT_MIGRATION_B64', encoded)
    restore_backup()
    assert db.get_project(pid)['title'] == '用户新标题'
    assert len(db.get_messages(pid)) == 1
