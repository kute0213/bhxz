"""
验证码服务模块：生成带干扰线条的数学题验证码图片。

图片直接返回 base64 编码，不保存文件，减少服务器开销。
验证码答案存于服务端内存（CaptchaService 单例），返回随机 captcha_id
供前端提交时携带，校验后一次性删除防止重放攻击，避免被 curl 等工具绕过。
"""

import io
import base64
import random
import time
import uuid
import threading
from typing import Tuple

# 延迟导入 Pillow，避免不必要的依赖检查
_pil_available = None
Image = None
ImageDraw = None
ImageFont = None


def _check_pil():
    """检查 Pillow 是否可用，延迟加载。"""
    global _pil_available, Image, ImageDraw, ImageFont
    if _pil_available is None:
        try:
            from PIL import Image as _Image
            from PIL import ImageDraw as _ImageDraw
            from PIL import ImageFont as _ImageFont
            Image = _Image
            ImageDraw = _ImageDraw
            ImageFont = _ImageFont
            _pil_available = True
        except ImportError:
            _pil_available = False
    return _pil_available


def generate_math_captcha(
    width: int = 200,
    height: int = 50,
    min_num: int = 1,
    max_num: int = 9,
    line_count: int = 3,
    point_count: int = 60,
) -> Tuple[str, str]:
    """
    生成简单个位数加法验证码图片。

    使用单位数运算（1-9），答案范围 2-18，简单易识别。
    干扰线条和点较少，文字清晰。

    Args:
        width: 图片宽度
        height: 图片高度
        min_num: 最小数字（默认单位数 1）
        max_num: 最大数字（默认单位数 9）
        line_count: 干扰线条数量
        point_count: 干扰点数量

    Returns:
        (answer, base64_image): 答案字符串和 base64 编码的图片

    Raises:
        RuntimeError: Pillow 库未安装
    """
    if not _check_pil():
        raise RuntimeError("Pillow 库未安装，请运行: pip install Pillow")

    # 生成随机个位数加法（答案范围 2-18）
    a = random.randint(min_num, max_num)
    b = random.randint(min_num, max_num)
    answer = str(a + b)
    question = f"{a} + {b} = ?"

    # 创建图片
    img = Image.new('RGB', (width, height), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)

    # 尝试使用系统字体，失败则使用默认字体
    font_size = max(22, height // 2 + 2)
    try:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:\\Windows\\Fonts\\Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        font = None
        for path in font_paths:
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # 绘制少量干扰点（颜色较浅，不影响识别）
    for _ in range(point_count):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = (random.randint(180, 210), random.randint(180, 210), random.randint(180, 210))
        draw.point((x, y), fill=color)

    # 绘制少量干扰线（颜色较浅）
    for _ in range(line_count):
        x1 = random.randint(0, width // 2)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(width // 2, width - 1)
        y2 = random.randint(0, height - 1)
        color = (random.randint(160, 200), random.randint(160, 200), random.randint(160, 200))
        draw.line((x1, y1, x2, y2), fill=color, width=1)

    # 绘制文字（居中，深色清晰）
    text_bbox = draw.textbbox((0, 0), question, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2 - 2

    # 文字阴影效果
    draw.text((x + 1, y + 1), question, font=font, fill=(180, 180, 180))
    # 主文字（深色，清晰可读）
    draw.text((x, y), question, font=font, fill=(30, 30, 30))

    # 转换为 base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return answer, f"data:image/png;base64,{base64_data}"


def verify_captcha(user_input: str, answer: str, created_at: float = None) -> bool:
    """
    验证用户输入的验证码是否正确。

    支持时间戳校验：当传入 created_at 时，检查是否超过 300 秒过期。

    Args:
        user_input: 用户输入
        answer: 正确答案
        created_at: 验证码生成时间戳（秒），传入则校验是否过期（300 秒）

    Returns:
        是否正确
    """
    if not user_input or not answer:
        return False
    # 时间戳校验：超过 300 秒视为过期
    if created_at is not None and (time.time() - created_at) > 300:
        return False
    return user_input.strip() == answer.strip()


class CaptchaService:
    """图形验证码管理器（单例，服务端内存存储，自动过期清理，线程安全）。

    存储结构：{captcha_id: {'answer': str, 'expire': float, 'created_at': float}}
    答案不再依赖 session，防止被 curl 等工具绕过。

    安全特性：
    - 验证码答案仅在服务端内存中，不返回给客户端
    - 使用随机 UUID 作为 captcha_id，无法预测
    - verify() 校验后一次性删除，防止重放攻击
    - 过期时间 300 秒，超时自动失效
    - 后台线程定期清理过期项，避免内存泄漏
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # {captcha_id: {'answer': str, 'expire': float, 'created_at': float}}
        self._captchas: dict = {}
        self._lock = threading.Lock()
        # 过期时间（秒）
        self._expire_seconds = 300
        # 启动后台清理线程，每 60 秒清理一次过期验证码，避免内存泄漏
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name='captcha-cleanup', daemon=True
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        """后台线程：定期清理过期验证码，避免内存泄漏。"""
        while True:
            time.sleep(60)
            try:
                self.cleanup_expired()
            except Exception as e:
                # 后台线程不应因异常退出
                print(f'[Captcha] 清理过期验证码失败: {e}', flush=True)

    def generate(self) -> Tuple[str, str, str]:
        """生成验证码。

        Returns:
            (captcha_id, answer, image_base64): UUID 验证码 ID、答案、base64 图片
        """
        answer, image_data = generate_math_captcha()
        captcha_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._captchas[captcha_id] = {
                'answer': answer,
                'expire': now + self._expire_seconds,
                'created_at': now,
            }
        return captcha_id, answer, image_data

    def verify(self, captcha_id: str, user_input: str) -> bool:
        """校验验证码并一次性删除（防止重放攻击）。

        Args:
            captcha_id: 验证码 ID
            user_input: 用户输入

        Returns:
            是否正确
        """
        if not captcha_id or not user_input:
            return False
        with self._lock:
            # 一次性取出并删除，无论校验是否成功都防止重放
            entry = self._captchas.pop(captcha_id, None)
            if not entry:
                return False
            # 过期校验
            if time.time() > entry['expire']:
                return False
            return user_input.strip() == entry['answer'].strip()

    def cleanup_expired(self):
        """清理过期的验证码。"""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._captchas.items() if now > v['expire']]
            for k in expired:
                del self._captchas[k]


# 全局单例
captcha_service = CaptchaService()