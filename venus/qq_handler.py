"""Venus QQ private-message handler."""

import asyncio


def _is_filled_str(value):
    return isinstance(value, str) and value.strip() != ''


class QQHandler:
    def __init__(self, reply, send, max_history=1024):
        if not callable(reply):
            raise TypeError('reply must be callable')
        if not callable(send):
            raise TypeError('send must be callable')
        if not isinstance(max_history, int) or isinstance(max_history, bool):
            raise TypeError('max_history must be an integer')
        if max_history <= 0:
            raise ValueError('max_history must be positive')
        self._reply = reply
        self._send = send
        self._max_history = max_history
        self._seen = {}
        self._in_flight = set()
        self._locks = {}

    async def handle(self, message_id, user_id, text):
        if not _is_filled_str(message_id) or not _is_filled_str(user_id):
            return
        if not isinstance(text, str) or text.strip() == '':
            return
        text = text.strip()

        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock

        async with lock:
            if message_id in self._seen or message_id in self._in_flight:
                return
            self._in_flight.add(message_id)
            try:
                answer = await self._process(message_id, user_id, text)
            except asyncio.CancelledError:
                self._in_flight.discard(message_id)
                raise
            except Exception:
                self._in_flight.discard(message_id)
                return
            self._in_flight.discard(message_id)
            self._remember(message_id)

    async def _process(self, message_id, user_id, text):
        answer = await self._reply(user_id, text)
        if not isinstance(answer, str) or answer.strip() == '':
            return None
        await self._send(user_id, message_id, answer)
        return answer

    def _remember(self, message_id):
        self._seen.pop(message_id, None)
        self._seen[message_id] = None
        while len(self._seen) > self._max_history:
            self._seen.pop(next(iter(self._seen)))
