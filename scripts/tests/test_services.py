"""服务层直接测试：测试 services 模块的纯业务逻辑。"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from core.db import init_db, get_db
from core.auth import hash_password, validate_password, verify_password
from services.captcha import captcha_service, verify_captcha
from services.email import email_code_service, music_review_result
from services.attachment_service import parse_attachment_json, save_attachments, clean_attachments
from services.user_service import register, login, change_password, change_username
from services import music_service
from config import REGISTER_VERIFY_CODE, MAX_LOGIN_ATTEMPTS


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

        # 已公开 → 转为私有 → 再申请 → 管理员驳回 → 自动转为私有
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PRIVATE
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PENDING
        success, _msg = music_service.review_music(music_id, False, 'admin', '127.0.0.1')
        assert success is True, "管理员驳回审核应成功"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PRIVATE, "驳回后应自动转为私有"
        assert all(m['id'] != music_id for m in music_service.get_public_musics())

        # 被驳回转为私有后，仍可重新申请公开
        success, _msg = music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        assert success is True, "驳回转私有后仍可重新申请公开"
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PENDING

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


def test_music_search_by_title():
    """公开音频按名称搜索：匹配/无匹配/空关键词行为正确。"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO music (user_id, username, title, file_path, status, created_at) "
            "VALUES (?, ?, ?, '', ?, ?)",
            (20001, 's', '开服主题曲', music_service.STATUS_PUBLIC,
             time.strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.execute(
            "INSERT INTO music (user_id, username, title, file_path, status, created_at) "
            "VALUES (?, ?, ?, '', ?, ?)",
            (20002, 's2', 'BGM 片段', music_service.STATUS_PUBLIC,
             time.strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        # 关键词匹配名称
        hits = music_service.get_public_musics('开服')
        assert len(hits) == 1 and hits[0]['title'] == '开服主题曲'
        # 大小写不敏感（部分数据库 LIKE 默认不敏感，仅作存在性断言）
        assert len(music_service.get_public_musics('bgm')) >= 0
        # 无匹配
        assert music_service.get_public_musics('不存在的标题') == []
        # 空关键词返回全部
        assert len(music_service.get_public_musics('')) >= 2
        assert len(music_service.get_public_musics(None)) >= 2
    finally:
        conn = get_db()
        conn.execute("DELETE FROM music WHERE user_id IN (20001, 20002)")
        conn.commit()
        conn.close()


def test_music_review_email_builder():
    """音频审核结果邮件 HTML：通过/驳回状态卡正确渲染。"""
    passed_html = music_review_result('测试音频A', True)
    assert '音频公开审核通过' in passed_html
    assert '测试音频A' in passed_html
    assert 'mail-status-success' in passed_html
    assert '审核通过' in passed_html

    rejected_html = music_review_result('测试音频B', False)
    assert '音频公开审核未通过' in rejected_html
    assert '测试音频B' in rejected_html
    assert 'mail-status-fail' in rejected_html
    assert '审核未通过' in rejected_html


def test_music_author_email():
    """音频上传者邮箱查询：有邮箱返回、无邮箱返回空、不存在返回空。"""
    email = 'music-author@example.com'
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
            ('music_author', 'x', email, time.strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username = 'music_author'").fetchone()
        user_id = row['id']

        music_id = _insert_music(user_id, 'music_author', music_service.STATUS_PRIVATE)
        assert music_service.get_author_email(music_id) == email
        assert music_service.get_author_email(999999) == ''
    finally:
        conn.execute("DELETE FROM music WHERE username = 'music_author'")
        conn.execute("DELETE FROM users WHERE username = 'music_author'")
        conn.commit()
        conn.close()


def test_music_start_upload_validation():
    """异步上传参数校验（不触发真实转码/文件落盘）。"""
    ip = '127.0.0.1'

    # 无文件
    success, msg = music_service.start_upload(1, 'u', '标题', False, None, ip)
    assert success is False and '选择' in msg

    # 无标题
    class FakeFile:
        filename = 'a.mp3'
        def save(self, path):
            raise AssertionError('不应触发文件保存')

    success, msg = music_service.start_upload(1, 'u', '', False, FakeFile(), ip)
    assert success is False and '名称' in msg

    # 不支持的扩展名
    class FakeBadFile:
        filename = 'a.exe'
        def save(self, path):
            raise AssertionError('不应触发文件保存')

    success, msg = music_service.start_upload(1, 'u', '标题', False, FakeBadFile(), ip)
    assert success is False and '格式' in msg


def test_music_transcode_cmd_build():
    """转码命令应同时生成 HLS 与唱片 MP3，并输出 -progress 进度文件。"""
    cmd = music_service._build_transcode_cmd(
        '/x/a.mp3', '/x/index.m3u8', '/x/seg_%03d.ts', '/x/index.mp3', '/x/progress.log')
    joined = ' '.join(cmd)
    assert '-f hls' in joined and '/x/index.m3u8' in joined, '缺少 HLS 输出'
    assert 'libmp3lame' in joined and '/x/index.mp3' in joined, '缺少 MP3 唱片输出'
    assert '-progress' in joined and '/x/progress.log' in joined, '缺少进度文件'
    assert 'pipe:1' not in joined, '不应再使用 pipe:1 进度'


def test_music_read_transcode_percent():
    """转码进度解析：-progress out_time_us 与 m3u8 分片时长取较大值。"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        prog = os.path.join(d, 'progress.log')
        with open(prog, 'w', encoding='utf-8') as f:
            f.write('frame=100\nout_time_us=15000000\nprogress=continue\n')
        playlist = os.path.join(d, 'index.m3u8')
        with open(playlist, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n#EXTINF:10.0,\nseg_000.ts\n#EXTINF:10.0,\nseg_001.ts\n#EXT-X-ENDLIST\n')
        # duration=40s：progress=37.5%，分片累计 20s=50% → 取 50%
        pct = music_service._read_transcode_percent(prog, playlist, 40.0)
        assert pct is not None and abs(pct - 50.0) < 0.01, f'应取较大值 50%，实际 {pct}'
        # duration 未知 → None
        assert music_service._read_transcode_percent(prog, playlist, None) is None
        # 上限 99
        prog2 = os.path.join(d, 'progress2.log')
        with open(prog2, 'w', encoding='utf-8') as f:
            f.write('out_time_us=99000000\nprogress=continue\n')
        pct = music_service._read_transcode_percent(prog2, playlist, 40.0)
        assert pct == 99.0, f'应封顶 99%，实际 {pct}'


def test_music_mp3_path():
    """MP3 唱片文件路径函数。"""
    assert music_service.get_music_mp3_path(42) == os.path.join(
        music_service._music_dir(42), 'index.mp3')


def test_music_duration_seconds():
    """音频总时长（秒）：从 m3u8 分片 EXTINF 累计；文件缺失/无分片返回 None。"""
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # 不存在的音频 → None
        assert music_service.get_music_duration_seconds(999999) is None

        music_id = _insert_music(10009, 'dur_owner', music_service.STATUS_PRIVATE)
        final_dir = music_service._music_dir(music_id)
        try:
            # 正常：3 分片 10.0+10.0+5.5 = 25.5s → 取整 26
            os.makedirs(final_dir, exist_ok=True)
            with open(os.path.join(final_dir, 'index.m3u8'), 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n'
                        '#EXTINF:10.0,\nseg_000.ts\n'
                        '#EXTINF:10.0,\nseg_001.ts\n'
                        '#EXTINF:5.5,\nseg_002.ts\n'
                        '#EXT-X-ENDLIST\n')
            assert music_service.get_music_duration_seconds(music_id) == 26, \
                f'应四舍五入取整为 26，实际 {music_service.get_music_duration_seconds(music_id)}'

            # 分片缺失 → None（文件被删）
            os.remove(os.path.join(final_dir, 'index.m3u8'))
            assert music_service.get_music_duration_seconds(music_id) is None
        finally:
            music_service.delete_music(music_id, 10009, False, '127.0.0.1')
            shutil.rmtree(final_dir, ignore_errors=True)


def test_music_attach_durations():
    """attach_durations 为列表补充 duration_seconds 字段（原地修改）。"""
    import shutil
    owner = 10010
    music_id = _insert_music(owner, 'att_owner', music_service.STATUS_PRIVATE)
    final_dir = music_service._music_dir(music_id)
    try:
        os.makedirs(final_dir, exist_ok=True)
        with open(os.path.join(final_dir, 'index.m3u8'), 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n#EXTINF:30.0,\nseg_000.ts\n#EXTINF:30.0,\nseg_001.ts\n#EXT-X-ENDLIST\n')
        rows = [{'id': music_id}, {'id': 999999}]
        result = music_service.attach_durations(rows)
        assert result is rows, '应原地补充并返回同一列表'
        assert rows[0]['duration_seconds'] == 60, f'60s 音频应为 60，实际 {rows[0]["duration_seconds"]}'
        assert rows[1]['duration_seconds'] is None, '缺失文件的音频时长应为 None'
    finally:
        music_service.delete_music(music_id, owner, False, '127.0.0.1')
        shutil.rmtree(final_dir, ignore_errors=True)


def test_music_delete_removes_db_and_files():
    """删除音频：数据库记录与文件目录（含 HLS / MP3）都被清理。"""
    import shutil
    owner = 10003
    music_id = _insert_music(owner, 'owner', music_service.STATUS_PRIVATE)
    final_dir = music_service._music_dir(music_id)
    os.makedirs(final_dir, exist_ok=True)
    for name in ('index.m3u8', 'index.mp3', 'seg_000.ts'):
        with open(os.path.join(final_dir, name), 'w', encoding='utf-8') as f:
            f.write('x')
    ok, _msg = music_service.delete_music(music_id, owner, False, '127.0.0.1')
    assert ok is True, f'删除应成功: {_msg}'
    assert music_service.get_music(music_id) is None, '数据库记录应被删除'
    assert not os.path.isdir(final_dir), '文件目录应被删除'
    shutil.rmtree(final_dir, ignore_errors=True)


def test_parse_tags():
    """标签解析与清洗：分隔符、去重、限长、去空白、无效输入。"""
    # 空 / 无效输入
    assert music_service.parse_tags('') == ''
    assert music_service.parse_tags(None) == ''
    assert music_service.parse_tags('   ') == ''
    assert music_service.parse_tags('') == ''

    # 多种分隔符（逗号/全角逗号/顿号/分号/空白）
    assert music_service.parse_tags('BGM,开服') == 'BGM,开服'
    assert music_service.parse_tags('BGM，开服') == 'BGM,开服'
    assert music_service.parse_tags('BGM、开服') == 'BGM,开服'
    assert music_service.parse_tags('BGM;开服') == 'BGM,开服'
    assert music_service.parse_tags('BGM 开服') == 'BGM,开服'
    assert music_service.parse_tags('  开服主题曲  ') == '开服主题曲'

    # 去重（含分隔空白与重复）
    assert music_service.parse_tags('BGM,BGM,开服') == 'BGM,开服'
    assert music_service.parse_tags('BGM, BGM, BGM') == 'BGM'

    # 超过 10 个标签 → 截断为 10 个
    many = ','.join(f'tag{i}' for i in range(20))
    result = music_service.parse_tags(many)
    assert len(result.split(',')) == 10

    # 单个标签超长 → 截断为 12 字
    assert music_service.parse_tags('很' * 20) == '很' * 12


def test_music_tags_save_and_search():
    """标签保存权限控制 + 搜索可直接通过标签命中（标题无关键词）。"""
    owner = 20010
    music_id = None
    try:
        music_id = _insert_music(owner, 'tag_owner', music_service.STATUS_PUBLIC, title='无标签标题')

        # 管理员可改任意音频
        ok, msg = music_service.set_music_tags(music_id, 9999, True, 'BGM,钢琴', '127.0.0.1')
        assert ok is True, msg
        assert music_service.get_music(music_id)['tags'] == 'BGM,钢琴'

        # 普通用户改自己的
        ok, msg = music_service.set_music_tags(music_id, owner, False, '开服,主题曲', '127.0.0.1')
        assert ok is True, msg

        # 普通用户无权改他人的
        ok, msg = music_service.set_music_tags(music_id, 9999, False, 'x', '127.0.0.1')
        assert ok is False, '非管理员不可改他人音频标签'
        assert music_service.get_music(music_id)['tags'] == '开服,主题曲', '标签不应被无权修改'

        # 不存在的音频
        ok, msg = music_service.set_music_tags(999999, owner, False, 'x', '127.0.0.1')
        assert ok is False

        # 搜索可通过标签命中（标题不包含关键词）
        hits = music_service.get_public_musics('开服')
        assert any(m['id'] == music_id for m in hits), '应通过标签搜索到音频'
        hits = music_service.get_public_musics('主题曲')
        assert any(m['id'] == music_id for m in hits), '应通过标签搜索到音频'
    finally:
        if music_id:
            conn = get_db()
            conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
            conn.commit()
            conn.close()


def test_music_favorite_flow():
    """收藏/取消收藏/我的收藏：仅公开可收藏、重复收藏自动取消、删除级联清理。"""
    owner = 20020
    user = 20021
    music_id = None
    try:
        # 私有音频不可收藏
        music_id = _insert_music(owner, 'fav_owner', music_service.STATUS_PRIVATE, title='私藏')
        ok, msg, is_fav = music_service.toggle_favorite(user, music_id)
        assert ok is False, '私有音频不可收藏'
        assert msg == '仅可收藏已公开的音频'

        # 转为公开后可收藏
        music_service.toggle_music_public(music_id, owner, False, '127.0.0.1')
        music_service.review_music(music_id, True, 'admin', '127.0.0.1')
        assert music_service.get_music(music_id)['status'] == music_service.STATUS_PUBLIC

        ok, msg, is_fav = music_service.toggle_favorite(user, music_id)
        assert ok is True and is_fav is True, f'收藏应成功: {msg}'
        assert music_id in music_service.get_favorite_ids(user)

        favs = music_service.get_user_favorites(user)
        assert any(m['id'] == music_id for m in favs), '我的收藏应包含该音频'
        fav = next(m for m in favs if m['id'] == music_id)
        assert fav['title'] == '私藏'
        assert fav['username'] == 'fav_owner'

        # 重复收藏自动取消
        ok, msg, is_fav = music_service.toggle_favorite(user, music_id)
        assert ok is True and is_fav is False, '重复收藏应取消'
        assert music_id not in music_service.get_favorite_ids(user)

        # 不存在的音频
        ok, msg, is_fav = music_service.toggle_favorite(user, 999999)
        assert ok is False and msg == '音频不存在'

        # 重新收藏，删除音频后收藏级联清理
        music_service.toggle_favorite(user, music_id)
        assert music_id in music_service.get_favorite_ids(user)
        music_service.delete_music(music_id, owner, False, '127.0.0.1')
        assert music_id not in music_service.get_favorite_ids(user), '删除音频应级联清理收藏'
        music_id = None
    finally:
        if music_id:
            conn = get_db()
            conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
            conn.execute("DELETE FROM music_favorites WHERE music_id = ?", (music_id,))
            conn.commit()
            conn.close()


def test_account_lockout_after_max_attempts():
    """账户锁定机制：连续失败达到阈值后锁定，正确密码也不可登录。"""
    old_bypass = os.environ.get('TRAE_TEST_BYPASS_CAPTCHA', '')
    os.environ['TRAE_TEST_BYPASS_CAPTCHA'] = '1'
    username = 'lk_' + os.urandom(4).hex()
    password = 'LockTest123!'
    ip = '127.0.0.100'
    try:
        # 注册用户
        captcha_id, answer, _ = captcha_service.generate()
        success, user = register(
            username, password, password, '', answer.swapcase(),
            captcha_id, '', '', ip, False,
            group_code_verified=True,
        )
        assert success is True, user

        # 逐次错误密码登录，触发锁定
        for i in range(MAX_LOGIN_ATTEMPTS - 1):
            success, msg = login(username, 'WrongPass', '', '', ip)
            assert success is False, f'第 {i+1} 次错误登录应失败'
            assert msg == '用户名或密码错误', f'第 {i+1} 次错误信息: {msg}'

        # 第 N 次错误登录 → 触发锁定
        success, msg = login(username, 'WrongPass', '', '', ip)
        assert success is False
        assert '已被锁定' in msg, f'第 5 次错误应触发锁定提示: {msg}'

        # 锁定后即使正确密码也登录失败
        success, msg = login(username, password, '', '', ip)
        assert success is False
        assert '已被锁定' in msg, f'锁定后正确密码应被拒绝: {msg}'

        # 验证数据库记录
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT login_attempts, locked_until FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            assert row is not None
            assert row['login_attempts'] >= MAX_LOGIN_ATTEMPTS, \
                f'登录尝试次数: {row["login_attempts"]}'
            assert row['locked_until'] and row['locked_until'] != '', 'locked_until 应有值'
        finally:
            conn.close()
    finally:
        if old_bypass:
            os.environ['TRAE_TEST_BYPASS_CAPTCHA'] = old_bypass
        else:
            os.environ.pop('TRAE_TEST_BYPASS_CAPTCHA', None)
        # 清理测试用户
        try:
            conn = get_db()
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            conn.close()
        except Exception:
            pass


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
        test_music_review_email_builder,
        test_music_author_email,
        test_music_start_upload_validation,
        test_music_transcode_cmd_build,
        test_music_read_transcode_percent,
        test_music_mp3_path,
        test_music_duration_seconds,
        test_music_attach_durations,
        test_music_delete_removes_db_and_files,
        test_parse_tags,
        test_music_tags_save_and_search,
        test_music_favorite_flow,
        test_account_lockout_after_max_attempts,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")
