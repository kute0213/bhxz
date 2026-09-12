"""图形验证码生成和校验测试。"""

import base64
from io import BytesIO

from PIL import Image

from services.captcha import captcha_service, generate_char_captcha, verify_captcha


def test_captcha_image_has_readable_dimensions():
    code, data_url = generate_char_captcha()
    assert len(code) == 4
    assert data_url.startswith('data:image/png;base64,')

    raw = base64.b64decode(data_url.split(',', 1)[1])
    with Image.open(BytesIO(raw)) as image:
        assert image.size == (420, 150)


def test_captcha_verification_is_case_insensitive():
    assert verify_captcha('abcd', 'ABCD')
    assert verify_captcha('ABCD', 'abcd')
    assert verify_captcha(' AbCd ', 'aBcD')


def test_captcha_refresh_can_consume_previous_code():
    captcha_id, answer, _image = captcha_service.generate()
    assert captcha_service.verify(captcha_id, answer.lower())
    captcha_service.consume(captcha_id)
    assert not captcha_service.verify(captcha_id, answer)


def test_captcha_is_removed_after_too_many_wrong_attempts():
    captcha_id, answer, _image = captcha_service.generate()
    wrong = 'AAAA' if answer.casefold() != 'aaaa' else 'CCCC'
    for _ in range(5):
        assert not captcha_service.verify(captcha_id, wrong)
    assert captcha_service.get_image(captcha_id) is None
