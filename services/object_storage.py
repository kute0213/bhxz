"""MinIO 用户图片存储服务。

Bucket 保持私有；数据库只保存对象键，浏览器通过站内受控路由读取图片。
"""

from io import BytesIO
from threading import RLock

from PIL import Image, ImageOps, UnidentifiedImageError

from config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    USER_IMAGE_MAX_BYTES,
)


class ObjectStorageError(RuntimeError):
    """对象存储配置、连接或图片处理失败。"""


class ObjectStorageService:
    """负责用户头像和背景图的校验、转换、上传与读取。"""

    _IMAGE_SPECS = {
        'avatar': {'size': (512, 512), 'quality': 88, 'crop': True},
        'background': {'size': (2560, 1440), 'quality': 90, 'crop': False},
    }

    def __init__(self):
        self._client = None
        self._bucket_ready = False
        self._lock = RLock()

    @property
    def configured(self):
        """访问密钥、Secret Key 和 Bucket 均存在时才启用 MinIO。"""
        return bool(MINIO_ENDPOINT and MINIO_ACCESS_KEY and MINIO_SECRET_KEY and MINIO_BUCKET)

    def _get_client(self):
        if not self.configured:
            raise ObjectStorageError('MinIO 尚未配置，请设置访问账号、密码和 Bucket')

        with self._lock:
            if self._client is None:
                try:
                    from minio import Minio
                    from urllib3 import PoolManager, Retry, Timeout
                except ImportError as exc:
                    raise ObjectStorageError('缺少 minio 依赖，请先安装 requirements.txt') from exc

                # 启动时会主动检查 MinIO，因此设置较短的连接超时，
                # 避免网络或安全组异常时阻塞整个网站启动。
                http_client = PoolManager(
                    timeout=Timeout(connect=3.0, read=5.0),
                    retries=Retry(total=1, connect=1, read=0, redirect=0),
                )
                self._client = Minio(
                    MINIO_ENDPOINT,
                    access_key=MINIO_ACCESS_KEY,
                    secret_key=MINIO_SECRET_KEY,
                    secure=MINIO_SECURE,
                    http_client=http_client,
                )
            return self._client

    def initialize(self):
        """应用启动时主动连接 MinIO 并确认 Bucket 可用。"""
        self._ensure_bucket()

    def _ensure_bucket(self):
        """首次使用时确认 Bucket；不存在则自动创建。"""
        if self._bucket_ready:
            return
        with self._lock:
            if self._bucket_ready:
                return
            try:
                client = self._get_client()
                if not client.bucket_exists(MINIO_BUCKET):
                    client.make_bucket(MINIO_BUCKET)
                self._bucket_ready = True
            except ObjectStorageError:
                raise
            except Exception as exc:
                raise ObjectStorageError(f'无法连接 MinIO Bucket：{exc}') from exc

    @staticmethod
    def _read_upload(upload):
        if not upload or not upload.filename:
            raise ObjectStorageError('请选择图片')

        raw = upload.stream.read(USER_IMAGE_MAX_BYTES + 1)
        if not raw:
            raise ObjectStorageError('上传的图片为空')
        if len(raw) > USER_IMAGE_MAX_BYTES:
            raise ObjectStorageError('图片不能超过 10MB')
        return raw

    def _convert_image(self, upload, kind):
        spec = self._IMAGE_SPECS.get(kind)
        if not spec:
            raise ObjectStorageError('不支持的图片类型')

        raw = self._read_upload(upload)
        try:
            image = Image.open(BytesIO(raw))
            if image.width * image.height > 40_000_000:
                raise ObjectStorageError('图片像素过大，请压缩后重试')
            image.verify()
            image = Image.open(BytesIO(raw))
            image = ImageOps.exif_transpose(image)
            image.load()
        except ObjectStorageError:
            raise
        except Image.DecompressionBombError as exc:
            raise ObjectStorageError('图片像素过大，请压缩后重试') from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ObjectStorageError('文件不是有效的图片') from exc

        if spec['crop']:
            image = ImageOps.fit(image, spec['size'], method=Image.Resampling.LANCZOS)
        else:
            image.thumbnail(spec['size'], Image.Resampling.LANCZOS)

        # WebP 支持透明通道；其余模式统一转成 RGB，避免调色板图片保存失败。
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

        output = BytesIO()
        image.save(output, format='WEBP', quality=spec['quality'], method=6)
        data = output.getvalue()
        if not data:
            raise ObjectStorageError('图片处理失败')
        return data

    def save_user_image(self, user_id, kind, upload):
        """转换并覆盖保存用户图片，返回数据库使用的对象键。"""
        data = self._convert_image(upload, kind)
        object_key = f'users/{int(user_id)}/{kind}.webp'
        self._ensure_bucket()
        try:
            self._get_client().put_object(
                MINIO_BUCKET,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type='image/webp',
            )
        except Exception as exc:
            raise ObjectStorageError(f'图片上传到 MinIO 失败：{exc}') from exc
        return object_key

    def get_object(self, object_key):
        """读取私有对象，返回 (bytes, content_type)。"""
        if not object_key:
            raise ObjectStorageError('图片不存在')
        self._ensure_bucket()
        response = None
        try:
            response = self._get_client().get_object(MINIO_BUCKET, object_key)
            data = response.read()
            return data, response.headers.get('content-type', 'application/octet-stream')
        except Exception as exc:
            raise ObjectStorageError(f'读取 MinIO 图片失败：{exc}') from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def delete_object(self, object_key):
        """删除对象；对象键为空时视为无需处理。"""
        if not object_key or not self.configured:
            return
        self._ensure_bucket()
        try:
            self._get_client().remove_object(MINIO_BUCKET, object_key)
        except Exception as exc:
            raise ObjectStorageError(f'删除 MinIO 图片失败：{exc}') from exc


object_storage = ObjectStorageService()
