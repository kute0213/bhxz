"""失败邮件重试队列测试 —— 落库、到期重发、次数上限与成功清理。"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from services.mail import retry

CREATE_TABLE = '''
    CREATE TABLE email_retry_queue (
        id INTEGER PRIMARY KEY,
        recipient TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        html TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        next_retry_at TEXT NOT NULL
    )
'''


@pytest.fixture
def retry_db(tmp_path, monkeypatch):
    """把重试模块的数据库访问指向临时库，并强制启用邮件功能。"""
    db_path = str(tmp_path / 'retry.db')

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def fake_transaction():
        conn = connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    conn = connect()
    conn.execute(CREATE_TABLE)
    conn.commit()
    conn.close()

    monkeypatch.setattr(retry, 'get_db', connect)
    monkeypatch.setattr(retry, 'transaction', fake_transaction)
    monkeypatch.setattr(retry, 'is_email_enabled', lambda: True)
    return db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute('SELECT * FROM email_retry_queue ORDER BY id').fetchall()
    finally:
        conn.close()


def _expire(db_path):
    """把 next_retry_at 调整到过去，模拟已到期。"""
    past = (datetime.now() - timedelta(seconds=1)).strftime(retry.TIME_FORMAT)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('UPDATE email_retry_queue SET next_retry_at = ?', (past,))
        conn.commit()
    finally:
        conn.close()


class TestRecordFailure:
    """发送失败落库。"""

    def test_inserts_pending_row(self, retry_db):
        retry.record_failure('a@example.com', '主题', '正文', '<p>正文</p>',
                             RuntimeError('连接超时'))

        rows = _rows(retry_db)
        assert len(rows) == 1
        row = rows[0]
        assert row['recipient'] == 'a@example.com'
        assert row['subject'] == '主题'
        assert row['html'] == '<p>正文</p>'
        assert row['attempts'] == 0
        assert row['status'] == 'pending'
        assert '连接超时' in row['last_error']

    def test_first_retry_delayed(self, retry_db):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))

        row = _rows(retry_db)[0]
        created = datetime.strptime(row['created_at'], retry.TIME_FORMAT)
        due = datetime.strptime(row['next_retry_at'], retry.TIME_FORMAT)
        assert (due - created).total_seconds() == retry.RETRY_INTERVAL


class TestRetry:
    """定时任务重发。"""

    def test_success_deletes_row(self, retry_db, monkeypatch):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))
        _expire(retry_db)

        sent = []
        monkeypatch.setattr(retry, 'deliver', lambda item: sent.append(item))
        assert retry.retry_failed_emails() == 1
        assert sent[0]['to'] == 'a@example.com'
        assert _rows(retry_db) == []

    def test_failure_increments_attempts_and_delays(self, retry_db, monkeypatch):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))
        _expire(retry_db)

        def boom(item):
            raise ConnectionError('仍不可用')

        monkeypatch.setattr(retry, 'deliver', boom)
        assert retry.retry_failed_emails() == 0

        row = _rows(retry_db)[0]
        assert row['attempts'] == 1
        assert row['status'] == 'pending'
        assert '仍不可用' in row['last_error']
        due = datetime.strptime(row['next_retry_at'], retry.TIME_FORMAT)
        assert due > datetime.now()

    def test_stops_after_max_attempts(self, retry_db, monkeypatch):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))
        _expire(retry_db)
        conn = sqlite3.connect(retry_db)
        conn.execute('UPDATE email_retry_queue SET attempts = ?', (retry.MAX_ATTEMPTS - 1,))
        conn.commit()
        conn.close()

        monkeypatch.setattr(retry, 'deliver', lambda item: (_ for _ in ()).throw(ConnectionError('x')))
        retry.retry_failed_emails()

        row = _rows(retry_db)[0]
        assert row['attempts'] == retry.MAX_ATTEMPTS
        assert row['status'] == 'failed'

        # 已标记 failed 的记录不再被扫描
        _expire(retry_db)
        assert retry.retry_failed_emails() == 0

    def test_skips_when_email_disabled(self, retry_db, monkeypatch):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))
        _expire(retry_db)
        monkeypatch.setattr(retry, 'is_email_enabled', lambda: False)
        monkeypatch.setattr(retry, 'deliver', lambda item: pytest.fail('不应尝试发送'))
        assert retry.retry_failed_emails() == 0

    def test_not_due_rows_are_skipped(self, retry_db, monkeypatch):
        retry.record_failure('a@example.com', '主题', '正文', None, RuntimeError('x'))
        monkeypatch.setattr(retry, 'deliver', lambda item: pytest.fail('未到期不该发送'))
        assert retry.retry_failed_emails() == 0
        assert len(_rows(retry_db)) == 1
