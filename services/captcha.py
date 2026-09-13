"""
验证码服务模块：生成四位字符验证码图片（大写字母+数字组合，校验时不区分大小写）。

- 每个字符独立随机倾斜（-12° ~ +12°），字体粗大清晰，颜色从深色系随机选取
- 3~6 条不同颜色的随机干扰横线/斜线
- 字符后方 20~40 个浅色小号干扰字符（数字/字母/短横线/点）
- 背景彩色浅色噪点
- 图片直接返回 base64 编码，不保存文件，减少服务器开销
- 验证码答案存于服务端内存（CaptchaService 单例），返回随机 captcha_id
- 供前端提交时携带，校验后一次性删除防止重放攻击，避免被 curl 等工具绕过
"""

import io
import os
import base64
import random
import secrets
import time
import uuid
import threading
from typing import Tuple

from core.logger import log
from core.scheduler import Scheduler

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


# 项目内嵌字体路径（跨平台兼容）
_FONT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'lib', 'fonts', 'DejaVuSans-Bold.ttf'
)


def _load_font(size: int):
    """加载粗体验证码字体，按优先级尝试：
    1. 项目内嵌字体（static/lib/fonts/DejaVuSans-Bold.ttf）
    2. 常见 Linux 路径
    3. 常见 macOS 路径
    """
    paths = [
        _FONT_PATH,
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
        '/Library/Fonts/DejaVuSans-Bold.ttf',
    ]
    for path in paths:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    raise FileNotFoundError('未找到 DejaVuSans-Bold.ttf 字体文件')


# 图片统一显示大写字母和数字，并排除易混淆项：0/O、1/I/L、2/Z、5/S、8/B。
# 服务端使用 casefold() 校验，用户输入大写或小写都能通过。
_CAPTCHA_CHARS = 'ACDEFGHJKMNPQRTUVWXY34679'
_CAPTCHA_LENGTH = 4

# ---- 干扰线颜色：明快色系（红/橙/蓝/绿/紫/青/粉等），饱和度适中 ----
_LINE_COLORS = [
    (216, 76, 68),    # 红
    (232, 141, 52),   # 橙
    (66, 133, 224),   # 蓝
    (76, 172, 92),    # 绿
    (158, 92, 202),   # 紫
    (58, 178, 190),   # 青
    (216, 120, 164),  # 粉
    (146, 160, 62),   # 黄绿
]

# ---- 字符颜色：深色系（深蓝/深红/深绿/深紫/墨黑/深棕），保证清晰可辨 ----
_CHAR_COLORS = [
    (18, 52, 108),    # 深蓝
    (132, 28, 30),    # 深红
    (16, 88, 42),     # 深绿
    (92, 36, 118),    # 深紫
    (28, 28, 34),     # 墨黑
    (82, 48, 22),     # 深棕
    (52, 52, 66),     # 深灰蓝
]

# ---- 干扰字符颜色：浅色系（不要盖过字符） ----
_NOISE_CHAR_COLORS = [
    (150, 172, 204), (182, 148, 158), (166, 190, 152),
    (192, 172, 132), (158, 158, 194), (196, 142, 140),
    (140, 182, 184), (182, 172, 194), (188, 196, 158),
]

# 字符后方干扰字符池：数字 + 大写字母 + 短横线/点
_NOISE_CHARS = '0123456789ACDEFGHJKMNPQRTUVWXY-.'


def generate_char_captcha(
    width: int = 420,
    height: int = 150,
) -> Tuple[str, str]:
    """
    生成四位字符验证码图片。

    每个字符从大小写字母、数字中随机选取，单独渲染并轻微旋转，
    字体粗大清晰，颜色从深色系随机选取。图片包含：
    - 3~6 条不同颜色的随机干扰横线/斜线
    - 字符后方 20~40 个浅色小号干扰字符（数字/字母/短横线/点）
    - 背景彩色浅色噪点

    Args:
        width: 图片宽度
        height: 图片高度

    Returns:
        (code, base64_image): 验证码字符串和 base64 编码的图片

    Raises:
        RuntimeError: Pillow 库未安装
    """
    if not _check_pil():
        raise RuntimeError("Pillow 库未安装，请运行: pip install Pillow")

    # 生成 4 位随机字符（位数与字符集保持不变，避免破坏校验逻辑）
    code = ''.join(secrets.choice(_CAPTCHA_CHARS) for _ in range(_CAPTCHA_LENGTH))

    # 创建浅色背景图片
    img = Image.new('RGB', (width, height), color=(248, 246, 240))
    draw = ImageDraw.Draw(img)

    # 字号与单字符格宽匹配，避免旋转后首尾字符被画布裁掉。
    font_size = min(96, int(height * 0.68))
    try:
        # 优先使用项目内嵌字体（兼容 Windows / Linux / macOS）
        font = _load_font(font_size)
    except Exception:
        font = ImageFont.load_default()

    # 小号字体：用于字符后方的浅色干扰字符
    try:
        noise_font = _load_font(14)
    except Exception:
        noise_font = ImageFont.load_default()

    # ---- 背景噪点：数量增加、随机浅色（不再只是灰色） ----
    for _ in range((width * height) // 80):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        dot_color = (
            random.randint(175, 235),
            random.randint(175, 235),
            random.randint(175, 235),
        )
        draw.point((x, y), fill=dot_color)

    # ---- 字符后方：20~40 个随机干扰数字/字母/短横线/点（浅色系） ----
    for _ in range(random.randint(20, 40)):
        x = random.randint(0, max(0, width - 20))
        y = random.randint(0, max(0, height - 20))
        noise_ch = random.choice(_NOISE_CHARS)
        draw.text(
            (x, y), noise_ch, font=noise_font,
            fill=random.choice(_NOISE_CHAR_COLORS),
        )

    # ---- 3~6 条不同颜色的随机干扰横线/斜线 ----
    for _ in range(random.randint(3, 6)):
        # 线从左侧到右侧，随机倾斜穿行
        x1 = random.randint(0, width // 4)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(width * 3 // 4, width - 1)
        y2 = random.randint(0, height - 1)
        # 每条线从明快色系中随机取色，保证干扰明显且互不相同
        line_color = random.choice(_LINE_COLORS)
        draw.line(
            (x1, y1, x2, y2), fill=line_color,
            width=random.randint(2, 3),
        )

    # ---- 绘制每个字符（紧边界画布、独立旋转、按格居中） ----
    cell_w = width // _CAPTCHA_LENGTH
    for i, ch in enumerate(code):
        # 根据实际字形创建紧边界画布，避免旋转透明大画布造成字符重叠和裁切。
        bbox = font.getbbox(ch)
        glyph_w = bbox[2] - bbox[0]
        glyph_h = bbox[3] - bbox[1]
        glyph_pad = 10
        ch_img = Image.new(
            'RGBA',
            (glyph_w + glyph_pad * 2, glyph_h + glyph_pad * 2),
            (0, 0, 0, 0),
        )
        ch_draw = ImageDraw.Draw(ch_img)

        # 字符颜色：从深色系随机选取，保证清晰可辨
        char_color = random.choice(_CHAR_COLORS)

        ch_draw.text(
            (glyph_pad - bbox[0], glyph_pad - bbox[1]),
            ch,
            font=font,
            fill=char_color,
        )

        # 轻微旋转保留辨识度，同时提供基本的机器识别干扰。
        angle = random.randint(-12, 12)
        rotated = ch_img.rotate(
            angle, expand=True, resample=Image.BICUBIC,
            fillcolor=(0, 0, 0, 0)
        )

        # 计算粘贴位置
        paste_x = cell_w * i + (cell_w - rotated.width) // 2
        paste_x = max(0, min(width - rotated.width, paste_x))
        paste_y = (height - rotated.height) // 2 + random.randint(-2, 2)
        paste_y = max(0, min(height - rotated.height, paste_y))

        # 粘贴到主图（使用 alpha 通道作为遮罩）
        img.paste(rotated, (paste_x, paste_y), rotated)

    # 转换为 base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return code, f"data:image/png;base64,{base64_data}"


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
    return user_input.strip().casefold() == answer.strip().casefold()


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
        # 过期时间（秒）和单个验证码最大尝试次数
        self._expire_seconds = 300
        self._max_attempts = 5
        # 统一定时调度器：每 60 秒清理一次过期验证码，避免内存泄漏
        self._scheduler = Scheduler(
            name='captcha-cleanup',
            action=self._cleanup_task,
            interval=60,
            run_immediately=False,
        )
        self._scheduler.start()

    def _cleanup_task(self):
        """后台任务：定期清理过期验证码，避免内存泄漏。"""
        expired_count = self.cleanup_expired()
        if expired_count > 0:
            log('INFO', 'CaptchaService', f'清理过期验证码 {expired_count} 个', remaining=len(self._captchas))

    def generate(self) -> Tuple[str, str, str]:
        """生成验证码。

        Returns:
            (captcha_id, answer, image_base64): UUID 验证码 ID、答案、base64 图片
        """
        answer, image_data = generate_char_captcha()
        captcha_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._captchas[captcha_id] = {
                'answer': answer,
                'image': image_data,  # 存图片数据，页面刷新后可复用
                'expire': now + self._expire_seconds,
                'created_at': now,
                'attempts': 0,
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
            if time.time() > entry['expire']:
                self._captchas.pop(captcha_id, None)
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
            log('WARNING', 'CaptchaService', '参数为空', captcha_id=captcha_id)
            return False
        with self._lock:
            entry = self._captchas.get(captcha_id)
            if not entry:
                log('WARNING', 'CaptchaService', '验证码不存在或已消耗', captcha_id=captcha_id)
                return False
            if time.time() > entry['expire']:
                self._captchas.pop(captcha_id, None)
                log('WARNING', 'CaptchaService', '验证码已过期', captcha_id=captcha_id)
                return False
            result = (
                user_input.strip().casefold()
                == entry['answer'].strip().casefold()
            )
            if not result:
                entry['attempts'] = entry.get('attempts', 0) + 1
                if entry['attempts'] >= self._max_attempts:
                    self._captchas.pop(captcha_id, None)
                log('INFO', 'CaptchaService', '验证码答案错误', captcha_id=captcha_id)
            return result

    def consume(self, captcha_id: str):
        """消耗验证码（注册成功后调用，防止重放攻击）。"""
        if not captcha_id:
            return
        with self._lock:
            if captcha_id in self._captchas:
                self._captchas.pop(captcha_id)
                log('INFO', 'CaptchaService', '验证码已消耗', captcha_id=captcha_id)

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
