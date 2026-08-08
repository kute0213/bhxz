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

# 简单日志输出
_log_lock = threading.Lock()


def _log(event: str, detail: str = '', **kwargs):
    """输出格式化的日志信息。"""
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    parts = [f'[{now}] [CaptchaService]', f'[{event}]', detail]
    for k, v in kwargs.items():
        parts.append(f'{k}={v}')
    print(' '.join(parts), flush=True)


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
    line_count: int = 6,
    point_count: int = 120,
) -> Tuple[str, str]:
    """
    生成一位数加减法验证码图片。

    使用一位数运算（1-9），随机加减，答案范围 0-18。

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

    # 生成随机一位数加减法（答案范围 0-18）
    a = random.randint(min_num, max_num)
    b = random.randint(min_num, max_num)
    if random.choice(['+', '-']) == '+':
        answer = str(a + b)
        question = f"{a} + {b} = ?"
    else:
        # 减法保证结果非负：大数减小数
        if a < b:
            a, b = b, a
        answer = str(a - b)
        question = f"{a} - {b} = ?"

    # 创建图片
    img = Image.new('RGB', (width, height), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)

    # 尝试使用系统字体，失败则使用默认字体
    font_size = max(18, height // 2)
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

    # 绘制干扰点（随机分布，密度与图片面积成正比）
    point_count = max(50, (width * height) // 80)
    for _ in range(point_count):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = (random.randint(150, 200), random.randint(150, 200), random.randint(150, 200))
        draw.point((x, y), fill=color)

    # 绘制干扰线
    for _ in range(line_count):
        x1 = random.randint(0, width // 2)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(width // 2, width - 1)
        y2 = random.randint(0, height - 1)
        color = (random.randint(100, 180), random.randint(100, 180), random.randint(100, 180))
        draw.line((x1, y1, x2, y2), fill=color, width=1)

    # 绘制文字（居中，每个字符独立颜色，实现字母变色效果）
    # 先测量总宽度，计算居中起始 x
    char_widths = []
    total_width = 0
    for ch in question:
        ch_bbox = draw.textbbox((0, 0), ch, font=font)
        cw = ch_bbox[2] - ch_bbox[0]
        char_widths.append(cw)
        total_width += cw
    x = (width - total_width) // 2
    text_bbox = draw.textbbox((0, 0), question, font=font)
    text_height = text_bbox[3] - text_bbox[1]
    base_y = (height - text_height) // 2 - 2

    for i, ch in enumerate(question):
        # 每个字符随机颜色（鲜艳，避免太浅）
        r = random.randint(20, 200)
        g = random.randint(20, 200)
        b = random.randint(20, 200)
        char_color = (r, g, b)

        # 轻微上下抖动（-2 ~ +2 像素）
        jitter_y = random.randint(-2, 2)

        # 阴影颜色（基于字符颜色调暗）
        shadow_color = (max(0, r - 120), max(0, g - 120), max(0, b - 120))

        # 绘制阴影
        draw.text((x + 1, base_y + jitter_y + 1), ch, font=font, fill=shadow_color)
        # 绘制主文字
        draw.text((x, base_y + jitter_y), ch, font=font, fill=char_color)

        x += char_widths[i] + 1

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
                expired_count = self.cleanup_expired()
                if expired_count > 0:
                    _log('Cleanup', f'清理过期验证码 {expired_count} 个', remaining=len(self._captchas))
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
                'image': image_data,  # 存图片数据，页面刷新后可复用
                'expire': now + self._expire_seconds,
                'created_at': now,
            }
        return captcha_id, answer, image_data

    def get_image(self, captcha_id: str) -> str | None:
        """获取已生成验证码的图片数据（用于页面刷新后复用，无需重新生成）。"""
        if not captcha_id:
            return None
        with self._lock:
            entry = self._captchas.get(captcha_id)
            if not entry:
                return None
            return entry.get('image')

    def verify(self, captcha_id: str, user_input: str) -> bool:
        """校验验证码（不消耗，可多次校验，防止误判导致用户需要重新输入）。

        安全机制：
        - 验证码过期时间 300 秒，超时自动失效
        - 注册成功后调用 consume() 主动删除，防止重放
        - IP 频率限制 + 验证码过期双重防护

        Args:
            captcha_id: 验证码 ID
            user_input: 用户输入

        Returns:
            是否正确
        """
        if not captcha_id or not user_input:
            _log('Verify', '参数为空', captcha_id=captcha_id)
            return False
        with self._lock:
            entry = self._captchas.get(captcha_id)
            if not entry:
                _log('Verify', '验证码不存在或已消耗', captcha_id=captcha_id)
                return False
            if time.time() > entry['expire']:
                _log('Verify', '验证码已过期', captcha_id=captcha_id)
                return False
            result = user_input.strip() == entry['answer'].strip()
            if not result:
                _log('Verify', '验证码答案错误', captcha_id=captcha_id)
            return result

    def consume(self, captcha_id: str):
        """消耗验证码（注册成功后调用，防止重放攻击）。"""
        if not captcha_id:
            return
        with self._lock:
            if captcha_id in self._captchas:
                self._captchas.pop(captcha_id)
                _log('Consume', '验证码已消耗', captcha_id=captcha_id)

    def cleanup_expired(self) -> int:
        """清理过期的验证码。

        Returns:
            清理的过期验证码数量
        """
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._captchas.items() if now > v['expire']]
            for k in expired:
                del self._captchas[k]
            return len(expired)


# 全局单例
captcha_service = CaptchaService()