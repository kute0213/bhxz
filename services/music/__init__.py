"""大喇叭音频业务服务包。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
音频文件存放在 uploads/music/<音频ID>/ 目录，播放链接格式：
http://<主机>/music/<音频ID>.m3u8
"""

from services.music.constants import (
    HLS_SEGMENT_SECONDS,
    STATUS_PRIVATE,
    STATUS_PENDING,
    STATUS_PUBLIC,
    STATUS_REJECTED,
    STATUS_LABELS,
)
from services.music.queries import (
    parse_tags,
    tags_to_list,
    get_public_musics,
    get_user_musics,
    get_pending_musics,
    get_all_musics,
    get_music,
    get_music_file_path,
    get_music_mp3_path,
    get_music_duration_seconds,
    attach_durations,
    get_author_email,
)
from services.music.favorites import (
    toggle_favorite,
    get_favorite_ids,
    get_user_favorites,
)
from services.music.upload import (
    upload_music,
    start_upload,
    get_upload_progress,
)
from services.music.crud import (
    delete_music,
    toggle_music_public,
    review_music,
    set_music_tags,
)

__all__ = [
    # constants
    'HLS_SEGMENT_SECONDS', 'STATUS_PRIVATE', 'STATUS_PENDING', 'STATUS_PUBLIC',
    'STATUS_REJECTED', 'STATUS_LABELS',
    # queries
    'parse_tags', 'tags_to_list', 'get_public_musics', 'get_user_musics',
    'get_pending_musics', 'get_all_musics', 'get_music', 'get_music_file_path',
    'get_music_mp3_path', 'get_music_duration_seconds', 'attach_durations',
    'get_author_email',
    # favorites
    'toggle_favorite', 'get_favorite_ids', 'get_user_favorites',
    # upload
    'upload_music', 'start_upload', 'get_upload_progress',
    # crud
    'delete_music', 'toggle_music_public', 'review_music', 'set_music_tags',
]