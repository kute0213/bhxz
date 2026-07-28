"""
验证码服务模块：生成带干扰线条的数学题验证码图片。

图片直接返回 base64 编码，不保存文件，减少服务器开销。
"""

import io
import base64
import random
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
    max_num: int = 10,
    line_count: int = 6,
    point_count: int = 120,
) -> Tuple[str, str]:
    """
    生成数学加法验证码图片。

    Args:
        width: 图片宽度
        height: 图片高度
        min_num: 最小数字
        max_num: 最大数字
        line_count: 干扰线条数量
        point_count: 干扰点数量

    Returns:
        (answer, base64_image): 答案字符串和 base64 编码的图片

    Raises:
        RuntimeError: Pillow 库未安装
    """
    if not _check_pil():
        raise RuntimeError("Pillow 库未安装，请运行: pip install Pillow")

    # 生成随机数学题
    a = random.randint(min_num, max_num)
    b = random.randint(min_num, max_num)
    answer = str(a + b)
    question = f"{a} + {b} = ?"

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

    # 绘制文字（居中）
    text_bbox = draw.textbbox((0, 0), question, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2 - 2

    # 文字阴影效果
    draw.text((x + 1, y + 1), question, font=font, fill=(150, 150, 150))
    # 主文字
    draw.text((x, y), question, font=font, fill=(30, 30, 30))

    # 转换为 base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return answer, f"data:image/png;base64,{base64_data}"


def verify_captcha(user_input: str, answer: str) -> bool:
    """
    验证用户输入的验证码是否正确。

    Args:
        user_input: 用户输入
        answer: 正确答案

    Returns:
        是否正确
    """
    if not user_input or not answer:
        return False
    return user_input.strip() == answer.strip()