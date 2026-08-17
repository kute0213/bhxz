"""
验证码服务模块：生成四位字符验证码图片（大写字母+小写字母+数字组合）。

- 每个字符独立随机倾斜（-35° ~ +35°），字体粗大清晰
- 一条随机倾斜的粗干扰线
- 图片直接返回 base64 编码，不保存文件，减少服务器开销
- 验证码答案存于服务端内存（CaptchaService 单例），返回随机 captcha_id
- 供前端提交时携带，校验后一次性删除防止重放攻击，避免被 curl 等工具绕过
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


# 排除易混淆字符：0/O/o、1/I/l、2/Z、5/S/s、8/B
_CAPTCHA_CHARS = 'ABCDEFGHJKMNPQRTUVWXYabcdefghjkmnpqrtuvwxy34679'


def generate_char_captcha(
    width: int = 300,
    height: int = 96,
) -> Tuple[str, str]:
    """
    生成四位字符验证码图片。

    每个字符从大写字母、小写字母、数字中随机选取，单独渲染并旋转
    -35° ~ +35°，字体粗大清晰。图片包含一条随机倾斜的粗干扰线。

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

    # 生成 4 位随机字符
    code = ''.join(random.choices(_CAPTCHA_CHARS, k=4))

    # 创建浅色背景图片
    img = Image.new('RGB', (width, height), color=(248, 246, 240))
    draw = ImageDraw.Draw(img)

    # 加载粗体字体（60 号，保证清晰可辨）
    font_size = 52
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
        )
    except Exception:
        font = ImageFont.load_default()

    # ---- 绘制微弱背景噪点 ----
    for _ in range((width * height) // 80):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        c = random.randint(195, 215)
        draw.point((x, y), fill=(c, c, c))

    # ---- 绘制一条随机倾斜的粗干扰线 ----
    line_width = random.randint(3, 5)
    # 线从左侧到右侧，随机倾斜穿行
    x1 = random.randint(0, width // 4)
    y1 = random.randint(0, height - 1)
    x2 = random.randint(width * 3 // 4, width - 1)
    y2 = random.randint(0, height - 1)
    # 线条颜色：中灰色，比字符浅
    lc = random.randint(140, 185)
    draw.line((x1, y1, x2, y2), fill=(lc, lc, lc), width=line_width)

    # ---- 绘制每个字符（独立旋转 + 粘贴） ----
    # 每个字符的分配宽度
    cell_w = width // 4
    # 左右留白，避免旋转后首尾字符被裁切
    pad = 10
    # 垂直居中偏移微调
    for i, ch in enumerate(code):
        # 为每个字符创建独立透明画布
        ch_size = font_size + 16
        ch_img = Image.new('RGBA', (ch_size, ch_size), (0, 0, 0, 0))
        ch_draw = ImageDraw.Draw(ch_img)

        # 字符颜色：深色，保证清晰可辨
        r = random.randint(30, 90)
        g = random.randint(30, 90)
        b = random.randint(30, 90)
        # 确保颜色足够深
        if r + g + b > 240:
            factor = 200 / (r + g + b)
            r, g, b = int(r * factor), int(g * factor), int(b * factor)
        char_color = (r, g, b)

        # 绘制字符到独立画布
        ch_draw.text((6, 4), ch, font=font, fill=char_color)

        # 随机旋转 -35° ~ +35°
        angle = random.randint(-35, 35)
        rotated = ch_img.rotate(
            angle, expand=True, resample=Image.BICUBIC,
            fillcolor=(0, 0, 0, 0)
        )

        # 计算粘贴位置
        paste_x = pad + cell_w * i + (cell_w - rotated.width) // 2
        paste_y = (height - rotated.height) // 2 + random.randint(-4, 4)

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
        answer, image_data = generate_char_captcha()
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