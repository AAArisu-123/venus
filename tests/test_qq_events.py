"""Tests for the independent QQ C2C inbound event validator."""

import contextlib
import io
import unittest

from venus.qq_events import parse_c2c_event


def c2c_data(**overrides):
    """Return the inner ``data`` object of an official-style C2C message event.

    Field names follow the QQ bot OpenAPI single-chat (c2c) message payload:
    ``id``, ``author.user_openid``, ``content`` plus the scene fields
    such as ``attachments``.
    """
    data = {
        'id': 'B6A1D0C4F3E24D8A9B7C6E5F4D3A2B10',
        'author': {
            'user_openid': 'E4A5B6C7D8E9F0A1B2C3D4E5F6A7B8C9',
            'union_openid': 'U-1234567890ABCDEF',
        },
        'content': '你好，Venus！',
        'message_type': 0,
        'message_scene': {'source': 'message'},
        'seq': 1,
        'attachments': [],
    }
    data.update(overrides)
    return data


class ParseC2CEventTests(unittest.TestCase):
    # 有效载荷
    def test_official_style_event_returns_triple(self):
        self.assertEqual(parse_c2c_event(c2c_data()), (
            'B6A1D0C4F3E24D8A9B7C6E5F4D3A2B10',
            'E4A5B6C7D8E9F0A1B2C3D4E5F6A7B8C9',
            '你好，Venus！',
        ))

    def test_body_text_is_stripped(self):
        self.assertEqual(parse_c2c_event(c2c_data(content='\n  hello world \t'))[2],
                         'hello world')

    # Unicode
    def test_unicode_content_and_identifiers_are_preserved(self):
        data = c2c_data(
            id='消息-ID-①',
            author={'user_openid': '用户_开放ID_😂'},
            content='  你好，世界！🌍  ',
        )
        self.assertEqual(parse_c2c_event(data),
                         ('消息-ID-①', '用户_开放ID_😂', '你好，世界！🌍'))

    def test_multiline_unicode_body(self):
        text = '第一行\n第二行\t第三行  结束'
        self.assertEqual(parse_c2c_event(c2c_data(content='  ' + text + '  '))[2], text)

    # 格式错误
    def test_non_mapping_inputs_return_none(self):
        for value in (None, [], 'text', 42, True, b'bytes'):
            with self.subTest(value=value):
                self.assertIsNone(parse_c2c_event(value))

    def test_missing_required_fields_return_none(self):
        self.assertIsNone(parse_c2c_event({}))
        self.assertIsNone(parse_c2c_event({'id': 'm1'}))
        self.assertIsNone(parse_c2c_event({'id': 'm1', 'author': {}}))
        self.assertIsNone(parse_c2c_event({'id': 'm1', 'author': {'user_openid': 'u1'}}))

    def test_author_not_a_mapping_returns_none(self):
        for author in (None, 'u1', 42, ['u1']):
            with self.subTest(author=author):
                self.assertIsNone(parse_c2c_event(c2c_data(author=author)))

    def test_outer_webhook_body_is_not_accepted(self):
        # Passing the whole webhook body (which nests ``data``) must not be
        # mistaken for the inner C2C data object the validator expects.
        event = {'id': 'event-id', 'type': 'message', 'source': 'c2c', 'data': c2c_data()}
        self.assertIsNone(parse_c2c_event(event))

    # 字段非字符串
    def test_non_string_required_fields_return_none(self):
        bad_values = (None, 1, 1.5, True, [], {}, b'bytes')
        for field in ('id', 'content'):
            for value in bad_values:
                with self.subTest(field=field, value=value):
                    self.assertIsNone(parse_c2c_event(c2c_data(**{field: value})))
        for value in bad_values:
            with self.subTest(field='user_openid', value=value):
                self.assertIsNone(parse_c2c_event(c2c_data(
                    author={'user_openid': value})))

    def test_blank_required_fields_return_none(self):
        blank_values = ('', '   ', '\n\t ')
        for field in ('id', 'content'):
            for value in blank_values:
                with self.subTest(field=field, value=value):
                    self.assertIsNone(parse_c2c_event(c2c_data(**{field: value})))
        for value in blank_values:
            with self.subTest(field='user_openid', value=value):
                self.assertIsNone(parse_c2c_event(c2c_data(
                    author={'user_openid': value})))

    # 附件无文本
    def test_attachment_only_message_returns_none(self):
        attachments = [{
            'content_type': 'image/png',
            'filename': 'photo.png',
            'url': 'https://example.invalid/photo.png',
        }]
        self.assertIsNone(parse_c2c_event(c2c_data(content='', attachments=attachments)))
        self.assertIsNone(parse_c2c_event(c2c_data(content='  \n ', attachments=attachments)))

    def test_text_inside_attachment_is_not_used_as_body(self):
        attachments = [{
            'content_type': 'voice',
            'content': '转写后的文字',
        }]
        self.assertIsNone(parse_c2c_event(c2c_data(content='', attachments=attachments)))

    def test_text_and_attachment_both_present_uses_text(self):
        parsed = parse_c2c_event(c2c_data(
            content=' 带图片的消息 ',
            attachments=[{'content_type': 'image/png'}],
        ))
        self.assertEqual(parsed[2], '带图片的消息')

    # 不打印、不存储：纯函数
    def test_does_not_print(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            parse_c2c_event(c2c_data())
        self.assertEqual(output.getvalue(), '')

    def test_does_not_mutate_input_or_keep_state(self):
        data = c2c_data()
        first = parse_c2c_event(data)
        second = parse_c2c_event(data)
        self.assertEqual(first, second)
        self.assertEqual(data, c2c_data())


if __name__ == '__main__':
    unittest.main()
