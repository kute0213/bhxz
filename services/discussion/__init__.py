"""讨论区业务服务包：帖子 CRUD、回复 CRUD、置顶/锁定、分类管理。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

from services.discussion.categories import (
    get_categories,
    get_category_dict,
    create_category,
    delete_category,
    get_categories_with_counts,
)
from services.discussion.topics import (
    get_topic_count,
    get_topics_page,
    get_topic_detail,
    create_topic,
    edit_topic,
    delete_topic,
    toggle_pin,
    toggle_lock,
)
from services.discussion.replies import (
    reply_to_topic,
    delete_reply,
    get_replies_page,
    get_new_replies,
)

__all__ = [
    'get_categories', 'get_category_dict', 'create_category', 'delete_category',
    'get_categories_with_counts',
    'get_topic_count', 'get_topics_page', 'get_topic_detail', 'create_topic',
    'edit_topic', 'delete_topic', 'toggle_pin', 'toggle_lock',
    'reply_to_topic', 'delete_reply', 'get_replies_page', 'get_new_replies',
]