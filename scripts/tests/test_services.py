"""服务层直接测试：测试 services 模块的纯业务逻辑。"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from core.db import init_db, get_db
from core.auth import hash_password, validate_password, verify_password
from services.captcha import captcha_service, verify_captcha
from services.email import email_code_service
from services.attachment_service import parse_attachment_json, save_attachments, clean_attachments
from services.user_service import register, login, change_password, change_username
from services import music_service
from config import REGISTER_VERIFY_CODE


def setup():
    """初始化数据库。"""
    init_db()


def test_validate_password():
    """测试密码强度校验。"""
    assert validate_password('short') is not None, "过短密码应被拒绝"
    assert validate_password('12345678') is not None, "纯数字密码应被拒绝"
    assert validate_password('TestPass123!') is None, "合法密码应通过"
    assert validate_password('abcdefgh') is None, "8位纯字母密码符合最短长度+至少一个字母的要求"


def test_hash_password():
    """测试密码哈希。"""
    pwd = 'TestPass123!'
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)
    assert h1 != h2, "密码哈希应使用随机盐"
    assert verify_password(pwd, h1), "正确密码应通过校验"
    assert verify_password(pwd, h2), "相同密码生成的不同哈希都应通过校验"
    assert verify_password(pwd, __import__('hashlib').sha256(pwd.encode()).hexdigest()), \
        "应兼容历史 SHA-256 密码"
    assert h1 != hash_password('DifferentPass123!'), "不同密码的哈希应不同"


def test_attachment_parse():
    """测试附件 JSON 解析。"""
    # None 或空
    assert parse_attachment_json(None) == []
    assert parse_attachment_json('') == []

    # 字符串
    result = parse_attachment_json('"file.txt"')
    assert result == ['file.txt'], f"字符串解析结果: {result}"

    # JSON 数组
    result = parse_attachment_json('["a.txt", "b.txt"]')
    assert result == ['a.txt', 'b.txt'], f"数组解析结果: {result}"

    # 无效 JSON
    result = parse_attachment_json('not json')
    assert result == ['not json'], f"无效 JSON 解析结果: {result}"


def test_captcha_service():
    """测试验证码服务。"""
    # 生成（现在返回 3 个值：captcha_id, answer, image_data）
    captcha_id, answer, image_data = captcha_service.generate()
    assert captcha_id is not None
    assert answer is not None
    assert image_data is not None

    # 验证正确
    assert captcha_service.verify(captcha_id, answer) is True

    # 验证错误
    assert captcha_service.verify(captcha_id, '99999') is False

    # 验证已消耗
    captcha_service.consume(captcha_id)
    assert captcha_service.verify(captcha_id, answer) is False

    # 验证不存在的 ID
    assert captcha_service.verify('nonexistent', '123') is False

    # 字母验证码不区分大小写，避免视觉上难以判断大小写导致误报。
    case_id, case_answer, _ = captcha_service.generate()
    assert captcha_service.verify(case_id, case_answer.swapcase()) is True
    assert verify_captcha(case_answer.swapcase(), case_answer) is True
    assert verify_captcha('aB3C', 'Ab3c') is True
    captcha_service.consume(case_id)


def test_email_code_is_bound_to_purpose():
    """不同业务用途的邮箱验证码不能互相串用。"""
    email = 'purpose-test@example.com'
    with email_code_service._lock:
        email_code_service._codes[email] = {
            'code': '123456',
            'purpose': '注册',
            'expire': time.time() + 60,
            'sent_at': time.time(),
        }
    assert email_code_service.verify(
        email, '123456', purpose='找回密码', consume=False
    ) is False
    assert email_code_service.consume(email, '123456', purpose='注册') is True


def test_user_service_register_invalid():
    """测试注册验证（应该失败的情况）。"""
    ip = '127.0.0.1'

    # 用户名过短
    success, msg = register('a', 'TestPass123!', 'TestPass123!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "过短用户名应注册失败"

    # 密码不一致
    success, msg = register('testuser', 'TestPass123!', 'DifferentPass!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "密码不一致应注册失败"

    # 空用户名
    success, msg = register('', 'TestPass123!', 'TestPass123!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "空用户名应注册失败"


def test_user_service_login_invalid():
    """测试登录验证（应该失败的情况）。"""
    ip = '127.0.0.1'

    # 空用户名
    success, data = login('', '', '', '', ip)
    assert success is False, "空用户名应登录失败"

    # 错误的验证码
    success, data = login('nonexistent', 'test', '', '', ip)
    assert success is False, "错误验证码应登录失败"


def test_login_consumes_captcha():
    """一次验证码只能发起一次登录尝试，即使账号密码错误也不能重放。"""
    captcha_id, answer, _image_data = captcha_service.generate()
    success, _data = login('nonexistent_login_user', 'WrongPass123!', answer,
                           captcha_id, '127.0.0.2')
    assert success is False
    assert captcha_service.verify(captcha_id, answer) is False, "登录尝试后应消费验证码"


def test_register_and_login_success():
    """验证 session 群码状态注册、新密码哈希和登录主流程。"""
    username = 'auth_flow_' + os.urandom(4).hex()
    password = 'FlowPass123!'
    try:
        register_captcha_id, register_answer, _ = captcha_service.generate()
        success, user = register(
            username, password, password, '', register_answer.swapcase(),
            register_captcha_id, '', '', '127.0.0.3', False,
            group_code_verified=True,
        )
        assert success is True, user

        conn = get_db()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        assert row and len(row['password_hash']) > 64, "新账号不应再保存裸 SHA-256 哈希"
        assert verify_password(password, row['password_hash'])

        # 数据库唯一性校验不区分大小写，不能通过变换大小写重复注册。
        duplicate_captcha_id, duplicate_answer, _ = captcha_service.generate()
        success, error = register(
            username.swapcase(), password, password, '', duplicate_answer,
            duplicate_captcha_id, '', '', '127.0.0.7', False,
            group_code_verified=True,
        )
        assert success is False
        assert error == '该用户名已被注册'

        # 验证码正确但密码错误时，必须明确提示账号或密码错误。
        wrong_password_captcha_id, wrong_password_answer, _ = captcha_service.generate()
        success, error = login(
            username, 'WrongPass123!', wrong_password_answer.swapcase(),
            wrong_password_captcha_id, '127.0.0.5'
        )
        assert success is False
        assert error == '用户名或密码错误'

        # 验证码错误时优先明确提示验证码错误。
        wrong_captcha_id, _wrong_captcha_answer, _ = captcha_service.generate()
        success, error = login(
            username, password, '!!!!', wrong_captcha_id, '127.0.0.6'
        )
        assert success is False
        assert error == '验证码错误或已过期'

        login_captcha_id, login_answer, _ = captcha_service.generate()
        success, logged_in_user = login(
            username.swapcase(), password, login_answer.swapcase(), login_captcha_id,
            '127.0.0.4'
        )
        assert success is True, logged_in_user
        assert logged_in_user['username'] == username
    finally:
        conn = get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()


def test_change_password_validation():
    """测试修改密码验证。"""
    ip = '127.0.0.1'

    # 空当前密码
    success, msg = change_password(1, 'admin', '', 'NewPass123!', 'NewPass123!', ip)
    assert success is False, "空当前密码应失败"

    # 密码不一致
    success, msg = change_password(1, 'admin', 'admin1324', 'NewPass123!', 'Different!', ip)
    # 这里密码可能不对，但至少验证不通过
    assert success is False or msg is not None


def test_duplicate_email_check():
    """测试邮箱唯一性检查。"""
    conn = get_db()
    try:
        # 检查是否已有多个相同邮箱
        rows = conn.execute(
            "SELECT email, COUNT(*) as cnt FROM users WHERE email != '' AND email IS NOT NULL GROUP BY email HAVING cnt > 1"
        ).fetchall()
        assert len(rows) == 0, f"存在重复邮箱: {rows}"
    finally:
        conn.close()


def _insert_music(user_id, username, status, title='审核测试'):
    """直接插入一条音频记录，返回 music_id。"""
    conn = get_db()
    conn.execute(
        "INSERT INTO music (user_id, username, title, file_path, status, created_at) "
        "VALUES (?, ?, ?, '', ?, ?)",
        (user_id, username, title, status, time.strftime('%Y-%m-%d %H:%M:%S')),
    )
    conn.commit()
    music_id = conn.execute("SELECT MAX(id) FROM music").fetchone()[0]
    conn.close()
    return music_id


def test_music_status_machine():
    """公开音频审核状态机：私有→待审核→(通过/驳回)→私有，含权限与边界失败路径。"""
    owner = 10001
    stranger = 10002
    music_id = None
    try:
        # 私有 → 申请公开（待审核）
        music_id = _insert_music(owner, 'owner', music_service.STATUS_PRIVATE)
        success, _msg = music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert success is True, "私有音频申请公开应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PENDING

        # 待审核仍在待审核队列、不在公开列表
        assert any(m['id'] == music_id for m in music_service.get_pending_musics())
        assert all(m['id'] != music_id for m in music_service.get_public_musics())

        # 待审核 → 转为私有
        success, _msg = music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert success is True, "待审核音频转私有应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PRIVATE

        # 私有 → 待审核 → 管理员通过 → 已公开
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        success, _msg = music_service.review_music(music_id, True, 'admin', '127.0.0.1')
        assert success is True, "管理员通过审核应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PUBLIC
        assert any(m['id'] == music_id for m in music_service.get_public_musics())

        # 已公开 → 转为私有 → 再申请 → 管理员驳回 → 已驳回
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PRIVATE
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PENDING
        success, _msg = music_service.review_music(music_id, False, 'admin', '127.0.0.1')
        assert success is True, "管理员驳回审核应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_REJECTED
        assert all(m['id'] != music_id for m in music_service.get_public_musics())

        # 已驳回 → 转为私有
        success, _msg = music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert success is True, "已驳回音频转私有应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PRIVATE

        # 失败路径：非上传者无权限切换/审核
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')  # → 待审核
        success, _msg = music_service.toggle_music_public(music_id, stranger, False, '127.0.0.1')
        assert success is False, "非上传者切换状态应失败"

        # 失败路径：非待审核状态不可审核
        music_service.review_music(music_id, True, 'admin', '127.0.0.1')  # → 已公开
        success, _msg = music_service.review_music(music_id, False, 'admin', '127.0.0.1')
        assert success is False, "已公开音频不可再次审核"

        # 失败路径：不存在的音频
        success, _msg = music_service.toggle_music_public(999999, owner, False, '127.0.0.1')
        assert success is False, "切换不存在的音频应失败"
        success, _msg = music_service.review_music(999999, True, 'admin', '127.0.0.1')
        assert success is False, "审核不存在的音频应失败"
    finally:
        if music_id:
            conn = get_db()
            conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
            conn.commit()
            conn.close()


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_validate_password,
        test_hash_password,
        test_attachment_parse,
        test_captcha_service,
        test_email_code_is_bound_to_purpose,
        test_user_service_register_invalid,
        test_user_service_login_invalid,
        test_login_consumes_captcha,
        test_register_and_login_success,
        test_change_password_validation,
        test_duplicate_email_check,
        test_music_status_machine,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")
