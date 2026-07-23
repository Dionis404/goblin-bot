"""Тесты для shared/telegram_posts.py: фильтр ссылок на Teletype/блог."""
from shared import telegram_posts


def test_plain_post_is_not_teletype():
    assert telegram_posts.is_teletype_link("Обычный пост про ферму") is False


def test_teletype_domain_in_text_is_filtered():
    assert telegram_posts.is_teletype_link("Читай тут: teletype.in/@urgsfl/some-article") is True


def test_blog_domain_in_text_is_filtered():
    assert telegram_posts.is_teletype_link("Новый гайд: blog.goblincodex.fun/guide") is True


def test_blog_domain_in_link_preview_is_filtered():
    assert telegram_posts.is_teletype_link(
        "Смотри новость", link_preview_href="https://blog.goblincodex.fun/news/1"
    ) is True
