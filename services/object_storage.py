"""MinIO 对象存储适配器。

业务表只保存 ``minio://<bucket>/<object_key>`` 引用，不保存凭据或临时 URL。
"""

from io import BytesIO
import threading

from minio import Minio

from config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)


_client = None
_client_lock = threading.Lock()


def is_enabled():
    """是否已完整配置 MinIO。"""
    values = (MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET)
    return all(values)


def _get_client():
    if not is_enabled():
        raise RuntimeError('MinIO 未配置，请设置 MINIO_ENDPOINT、MINIO_ACCESS_KEY 和 MINIO_SECRET_KEY')

    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = Minio(
                    MINIO_ENDPOINT,
                    access_key=MINIO_ACCESS_KEY,
                    secret_key=MINIO_SECRET_KEY,
                    secure=MINIO_SECURE,
                )
    return _client


def _validate_object_key(object_key):
    key = (object_key or '').strip().replace('\\', '/')
    if not key or key.startswith('/') or '..' in key.split('/'):
        raise ValueError('无效的 MinIO 对象键')
    return key


def make_reference(object_key, bucket=None):
    key = _validate_object_key(object_key)
    return f'minio://{bucket or MINIO_BUCKET}/{key}'


def parse_reference(reference):
    if not reference or not reference.startswith('minio://'):
        return None
    remainder = reference[len('minio://'):]
    bucket, separator, object_key = remainder.partition('/')
    if not separator or not bucket:
        raise ValueError('无效的 MinIO 对象引用')
    return bucket, _validate_object_key(object_key)


def put_bytes(object_key, data, content_type='application/octet-stream'):
    key = _validate_object_key(object_key)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError('上传内容必须是 bytes')

    client = _get_client()
    if not client.bucket_exists(MINIO_BUCKET):
        raise RuntimeError(f'MinIO 存储桶不存在: {MINIO_BUCKET}')

    payload = bytes(data)
    client.put_object(
        MINIO_BUCKET,
        key,
        BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )
    return make_reference(key)


def get_bytes(reference):
    parsed = parse_reference(reference)
    if not parsed:
        raise ValueError('不是 MinIO 对象引用')
    bucket, object_key = parsed
    response = _get_client().get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def remove(reference):
    parsed = parse_reference(reference)
    if not parsed:
        return False
    bucket, object_key = parsed
    _get_client().remove_object(bucket, object_key)
    return True
