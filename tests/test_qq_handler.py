"""Tests for the Venus QQ private-message handler core."""

import asyncio
import unittest

from venus.qq_handler import QQHandler


async def record(events, label):
    events.append(label)


class BasicHandlingTests(unittest.IsolatedAsyncioTestCase):
    def make(self, answer='你好呀'):
        self.replies = []
        self.sends = []

        async def reply(user_id, text):
            self.replies.append((user_id, text))
            return answer

        async def send(user_id, message_id, message):
            self.sends.append((user_id, message_id, message))

        self.reply_impl = reply
        self.send_impl = send
        return QQHandler(reply, send)

    async def test_valid_message_is_answered_once(self):
        handler = self.make()
        await handler.handle('m1', 'u1', '在吗')
        self.assertEqual(self.replies, [('u1', '在吗')])
        self.assertEqual(self.sends, [('u1', 'm1', '你好呀')])

    async def test_text_is_stripped_before_reply(self):
        handler = self.make()
        await handler.handle('m1', 'u1', '\n  在吗  \t')
        self.assertEqual(self.replies, [('u1', '在吗')])

    async def test_blank_or_non_string_text_is_ignored(self):
        handler = self.make()
        for text in ('', '   ', '\n\t ', None, 123, 1.5, True, [], {}, b'\xe4\xbd\xa0\xe5\xa5\xbd'):
            with self.subTest(text=text):
                await handler.handle('m1', 'u1', text)
        self.assertEqual(self.replies, [])
        self.assertEqual(self.sends, [])

    async def test_blank_or_non_string_ids_are_ignored(self):
        handler = self.make()
        for message_id in (None, '', '   ', 1, 1.0, True, [], {}):
            with self.subTest(message_id=message_id):
                await handler.handle(message_id, 'u1', 'hi')
        for user_id in (None, '', '  ', 1, 1.0, True, [], {}):
            with self.subTest(user_id=user_id):
                await handler.handle('m1', user_id, 'hi')
        self.assertEqual(self.replies, [])
        self.assertEqual(self.sends, [])

    async def test_useless_reply_results_are_not_sent(self):
        for answer in (None, '', '   ', '\n', 123, 1.5, [], {}, True):
            with self.subTest(answer=answer):
                handler = self.make(answer=answer)
                await handler.handle('m1', 'u1', 'hi')
                self.assertEqual(self.sends, [])

    async def test_plain_reply_text_is_sent_unchanged(self):
        handler = self.make(answer='  在的 \n')
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(self.sends, [('u1', 'm1', '  在的 \n')])

    async def test_constructor_rejects_uncallable_arguments(self):
        async def reply(user_id, text):
            return ''

        async def send(user_id, message_id, message):
            return None

        with self.assertRaises(TypeError):
            QQHandler(None, send)
        with self.assertRaises(TypeError):
            QQHandler(reply, 'not-callable')

    async def test_rejects_non_positive_history_limit(self):
        async def reply(user_id, text):
            return ''

        async def send(user_id, message_id, message):
            return None

        for limit in (0, -1):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    QQHandler(reply, send, max_history=limit)


class DuplicateMessageTests(unittest.IsolatedAsyncioTestCase):
    def make(self, **kwargs):
        self.replies = []
        self.sends = []

        async def reply(user_id, text):
            self.replies.append((user_id, text))
            return 'ok'

        async def send(user_id, message_id, message):
            self.sends.append((user_id, message_id, message))

        return QQHandler(reply, send, **kwargs)

    async def test_same_message_id_is_answered_once(self):
        handler = self.make()
        await handler.handle('m1', 'u1', 'first')
        await handler.handle('m1', 'u1', 'first')
        await handler.handle('m1', 'u1', 'different text, same id')
        self.assertEqual([t for _, t in self.replies], ['first'])
        self.assertEqual(self.sends, [('u1', 'm1', 'ok')])

    async def test_duplicate_is_answered_once_under_concurrency(self):
        handler = self.make()
        await asyncio.gather(*[handler.handle('m1', 'u1', 'hi') for _ in range(5)])
        self.assertEqual(len(self.replies), 1)
        self.assertEqual(len(self.sends), 1)

    async def test_distinct_message_ids_are_all_answered(self):
        handler = self.make()
        await asyncio.gather(*[
            handler.handle(f'm{i}', 'u1', f't{i}') for i in range(6)
        ])
        self.assertEqual(len(self.replies), 6)
        self.assertEqual(len(self.sends), 6)

    async def test_history_is_bounded_and_evicts_oldest(self):
        handler = self.make(max_history=2)
        for message_id in ('m1', 'm2', 'm3'):
            await handler.handle(message_id, 'u1', 'hi')
        self.assertEqual(len(self.replies), 3)

        # 'm1' was evicted, so it is treated as a new message again.
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(len(self.replies), 4)

        # 'm3' is still remembered and stays deduplicated.
        await handler.handle('m3', 'u1', 'hi')
        self.assertEqual(len(self.replies), 4)
        self.assertEqual(len(self.sends), 4)

    async def test_history_limit_of_one_keeps_only_last_message(self):
        handler = self.make(max_history=1)
        await handler.handle('m1', 'u1', 'a')
        await handler.handle('m2', 'u1', 'b')
        await handler.handle('m1', 'u1', 'a')
        self.assertEqual([t for _, t in self.replies], ['a', 'b', 'a'])


class PerUserSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_user_is_serialized_end_to_end(self):
        events = []

        async def reply(user_id, text):
            events.append(('start', text))
            await record(events, f'yield:{text}')
            await record(events, f'yield:{text}')
            events.append(('end', text))
            return f'answer:{text}'

        async def send(user_id, message_id, message):
            events.append(('send', message_id, message))

        handler = QQHandler(reply, send)
        await asyncio.gather(*[
            handler.handle(f'm{i}', 'u1', f't{i}') for i in range(4)
        ])
        self.assertEqual(events, [
            ('start', 't0'), 'yield:t0', 'yield:t0', ('end', 't0'), ('send', 'm0', 'answer:t0'),
            ('start', 't1'), 'yield:t1', 'yield:t1', ('end', 't1'), ('send', 'm1', 'answer:t1'),
            ('start', 't2'), 'yield:t2', 'yield:t2', ('end', 't2'), ('send', 'm2', 'answer:t2'),
            ('start', 't3'), 'yield:t3', 'yield:t3', ('end', 't3'), ('send', 'm3', 'answer:t3'),
        ])

    async def test_duplicate_message_never_enters_reply_twice(self):
        active = 0
        overlaps = []

        async def reply(user_id, text):
            nonlocal active
            if active:
                overlaps.append(user_id)
            active += 1
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            active -= 1
            return 'ok'

        async def send(user_id, message_id, message):
            return None

        handler = QQHandler(reply, send)
        await asyncio.gather(*[handler.handle('m1', 'u1', 'hi') for _ in range(6)])
        self.assertEqual(overlaps, [])

    async def test_different_users_do_not_wait_for_each_other(self):
        order = []

        async def reply(user_id, text):
            if user_id == 'u_slow':
                await asyncio.sleep(0.05)
                order.append('slow')
            else:
                order.append('fast')
            return 'ok'

        async def send(user_id, message_id, message):
            return None

        handler = QQHandler(reply, send)
        await asyncio.wait_for(asyncio.gather(
            handler.handle('m1', 'u_slow', 'hi'),
            handler.handle('m2', 'u_fast', 'hi'),
        ), timeout=2)
        self.assertEqual(order, ['fast', 'slow'])

    async def test_same_user_lock_is_reused_after_completion(self):
        events = []

        async def reply(user_id, text):
            events.append(text)
            await asyncio.sleep(0)
            return 'ok'

        async def send(user_id, message_id, message):
            return None

        handler = QQHandler(reply, send)
        for round_index in range(3):
            await asyncio.gather(*[
                handler.handle(f'r{round_index}-{i}', 'u1', f'r{round_index}-{i}') for i in range(3)
            ])
        self.assertEqual(events, ['r0-0', 'r0-1', 'r0-2', 'r1-0', 'r1-1', 'r1-2', 'r2-0', 'r2-1', 'r2-2'])


class FailureRetryTests(unittest.IsolatedAsyncioTestCase):
    def make(self, failures=1, fail_on_send=0):
        self.reply_calls = []
        self.send_calls = []

        async def reply(user_id, text):
            self.reply_calls.append((user_id, text))
            if len(self.reply_calls) <= failures:
                raise RuntimeError('internal boom TOKEN=secret')
            return 'ok'

        async def send(user_id, message_id, message):
            self.send_calls.append((user_id, message_id, message))
            if len(self.send_calls) <= fail_on_send:
                raise ValueError('send boom TOKEN=secret')

        return QQHandler(reply, send)

    async def test_reply_failure_is_contained_and_message_id_stays_retryable(self):
        handler = self.make(failures=1)
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(self.send_calls, [])

        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(len(self.reply_calls), 2)
        self.assertEqual(self.send_calls, [('u1', 'm1', 'ok')])

    async def test_send_failure_keeps_message_retryable(self):
        handler = self.make(failures=0, fail_on_send=1)
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(len(self.reply_calls), 1)
        self.assertEqual(len(self.send_calls), 1)

        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(len(self.reply_calls), 2)
        self.assertEqual(self.send_calls, [('u1', 'm1', 'ok'), ('u1', 'm1', 'ok')])

    async def test_repeated_failures_stay_retryable(self):
        handler = self.make(failures=3)
        for _ in range(3):
            await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(len(self.reply_calls), 3)
        self.assertEqual(self.send_calls, [])

        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(self.send_calls, [('u1', 'm1', 'ok')])

    async def test_exception_details_are_never_forwarded_to_the_user(self):
        sent = []

        async def reply(user_id, text):
            raise KeyError('missing persona file at C:/secret/path')

        async def send(user_id, message_id, message):
            sent.append(message)

        handler = QQHandler(reply, send)
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(sent, [])

    async def test_failed_reply_does_not_block_the_next_message_of_the_same_user(self):
        handler = self.make(failures=1)
        await handler.handle('m1', 'u1', 'a')
        await handler.handle('m2', 'u1', 'b')
        self.assertEqual([t for _, t in self.reply_calls], ['a', 'b'])
        self.assertEqual(self.send_calls, [('u1', 'm2', 'ok')])

    async def test_concurrent_retry_after_failure_succeeds_once(self):
        handler = self.make(failures=1)
        await handler.handle('m1', 'u1', 'hi')
        await asyncio.gather(*[handler.handle('m1', 'u1', 'hi') for _ in range(4)])
        self.assertEqual(len(self.reply_calls), 2)
        self.assertEqual(self.send_calls, [('u1', 'm1', 'ok')])

    async def test_cancellation_is_not_swallowed_and_releases_the_message_id(self):
        attempts = []
        sent = []

        async def reply(user_id, text):
            attempts.append(text)
            if len(attempts) == 1:
                raise asyncio.CancelledError()
            return 'ok'

        async def send(user_id, message_id, message):
            sent.append(message)

        handler = QQHandler(reply, send)
        with self.assertRaises(asyncio.CancelledError):
            await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(sent, [])

        # The in-flight marker was released, so the same id can be retried.
        await handler.handle('m1', 'u1', 'hi')
        self.assertEqual(sent, ['ok'])


if __name__ == '__main__':
    unittest.main()
