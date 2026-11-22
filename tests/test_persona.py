import json
import tempfile
import unittest
from pathlib import Path

from venus.persona import load_persona


class LoadPersonaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write(self, obj, *, raw=None):
        path = self.tmp / 'persona.json'
        path.write_text(raw if raw is not None else json.dumps(obj, ensure_ascii=False), encoding='utf-8')
        return path

    def test_valid_persona_returns_all_fields(self):
        path = self.write({'name': '星星', 'description': '爱读书的AI伴侣。', 'greeting': '你好', 'version': 2, 'tags': ['a', 'b']})
        data = load_persona(path)
        self.assertEqual(data['name'], '星星')
        self.assertEqual(data['description'], '爱读书的AI伴侣。')
        self.assertEqual(data['greeting'], '你好')
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['tags'], ['a', 'b'])

    def test_accepts_string_path_and_accepts_str_path(self):
        path = self.write({'name': 'V', 'description': 'Friendly'})
        self.assertEqual(load_persona(str(path))['name'], 'V')
        self.assertEqual(load_persona(path)['name'], 'V')

    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            load_persona(self.tmp / 'nope.json')

    def test_invalid_json_raises_json_error(self):
        with self.assertRaises(json.JSONDecodeError):
            load_persona(self.write(None, raw='{not json'))

    def test_non_object_json_raises_value_error(self):
        for raw in ('[1, 2]', '"text"', '42', 'null'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    load_persona(self.write(None, raw=raw))

    def test_missing_fields_raise_value_error(self):
        for obj in ({}, {'name': 'V'}, {'description': 'D'}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    load_persona(self.write(obj))

    def test_non_string_fields_raise_value_error(self):
        for obj in ({'name': 1, 'description': 'D'},
                    {'name': 'V', 'description': None},
                    {'name': ['V'], 'description': 'D'},
                    {'name': True, 'description': 'D'}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    load_persona(self.write(obj))

    def test_blank_fields_raise_value_error(self):
        for obj in ({'name': '', 'description': 'D'},
                    {'name': '   ', 'description': 'D'},
                    {'name': 'V', 'description': ''},
                    {'name': 'V', 'description': ' \n\t '}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    load_persona(self.write(obj))

    def test_description_length_boundary(self):
        at_limit = self.write({'name': 'V', 'description': 'x' * 12000})
        self.assertEqual(len(load_persona(at_limit)['description']), 12000)
        over_limit = self.write({'name': 'V', 'description': 'x' * 12001})
        with self.assertRaises(ValueError):
            load_persona(over_limit)

    def test_multibyte_description_counts_characters(self):
        path = self.write({'name': 'V', 'description': '你' * 12000}, raw=None)
        self.assertEqual(len(load_persona(path)['description']), 12000)

    def test_optional_style_fields_are_preserved(self):
        path = self.write({
            'name': 'V',
            'description': 'D',
            'style': '短句',
            'boundaries': '不替用户做医疗决定',
            'relationship_pace': '慢慢熟悉',
        })
        data = load_persona(path)
        self.assertEqual(data['style'], '短句')
        self.assertEqual(data['boundaries'], '不替用户做医疗决定')
        self.assertEqual(data['relationship_pace'], '慢慢熟悉')

    def test_optional_style_fields_are_validated(self):
        for obj in (
            {'name': 'V', 'description': 'D', 'style': 1},
            {'name': 'V', 'description': 'D', 'boundaries': ['x']},
            {'name': 'V', 'description': 'D', 'relationship_pace': None},
            {'name': 'V', 'description': 'D', 'style': 'x' * 2001},
            {'name': 'V', 'description': 'D', 'boundaries': 'x' * 2001},
            {'name': 'V', 'description': 'D', 'relationship_pace': 'x' * 1001},
        ):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    load_persona(self.write(obj))

    def test_optional_examples_and_post_history_are_preserved(self):
        path = self.write({
            'name': 'V',
            'description': 'D',
            'examples': [
                {'user': '今天有点累', 'assistant': '那就先歇会儿。'},
                {'user': '你想我了吗', 'assistant': '想了。'},
            ],
            'post_history_instructions': '【本轮提醒】短句。',
        })
        data = load_persona(path)
        self.assertEqual(len(data['examples']), 2)
        self.assertEqual(data['examples'][0]['user'], '今天有点累')
        self.assertEqual(data['post_history_instructions'], '【本轮提醒】短句。')

    def test_optional_examples_and_post_history_are_validated(self):
        cases = (
            {'examples': 'x'},
            {'examples': [{'user': 'a'}]},
            {'examples': [{'user': '', 'assistant': 'b'}]},
            {'examples': [{'user': 'a', 'assistant': ''}]},
            {'examples': [{'user': 1, 'assistant': 'b'}]},
            {'examples': [{'user': 'a', 'assistant': 'b'}] * 9},
            {'examples': [{'user': 'a' * 501, 'assistant': 'b'}]},
            {'examples': [{'user': 'a', 'assistant': 'b' * 1001}]},
            {'post_history_instructions': 1},
            {'post_history_instructions': 'x' * 1001},
        )
        for extra in cases:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    load_persona(self.write(dict({'name': 'V', 'description': 'D'}, **extra)))

    def test_optional_style_fields_accept_boundaries(self):
        path = self.write({
            'name': 'V',
            'description': 'D',
            'style': 'x' * 2000,
            'boundaries': 'x' * 2000,
            'relationship_pace': 'x' * 1000,
        })
        data = load_persona(path)
        self.assertEqual(len(data['style']), 2000)
        self.assertEqual(len(data['boundaries']), 2000)
        self.assertEqual(len(data['relationship_pace']), 1000)


if __name__ == '__main__':
    unittest.main()
