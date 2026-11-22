"""Windows Task Scheduler entry point for the QQ bot.

Only fixed status lines are written to the rotating log.
"""
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from logging.handlers import RotatingFileHandler
from pathlib import Path


class GatewayStatusOnly(logging.Filter):
    """Translate known SDK events, never persist SDK payloads or exceptions."""

    def filter(self, record):
        if record.name == 'venus.qq_service':
            return True
        if record.name == 'venus.proactive_runner':
            # The runner only logs fixed status strings plus an exception class
            # name; message text and credentials never pass through here.
            return record.getMessage().startswith('status: ')
        if record.name != 'botpy' or record.filename != 'gateway.py':
            return False
        message = record.getMessage().strip()
        if message.startswith('[botpy] 机器人「') and message.endswith('」启动成功！'):
            status = 'QQ gateway READY'
        elif message == '[botpy] 机器人重连成功!':
            status = 'QQ gateway RESUMED'
        elif message.startswith(('[botpy] websocket连接:', '[botpy] 关闭, 返回码:')):
            status = 'QQ gateway disconnected; SDK will retry'
        else:
            return False
        record.msg, record.args = status, ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def open_status_handler(folder):
    """Open the rotating status log, falling back to a writable folder.

    The scheduled task normally writes under ``%LOCALAPPDATA%\\Venus\\logs``.
    Some locked-down or redirected profiles refuse writes there even for the
    signed-in user; the bot must still start, so the log falls back to the
    system temporary directory and finally to the project's own ``logs``
    folder (ignored by ``.gitignore``) instead of taking the service down.
    """
    candidates = [folder]
    temp = os.environ.get('TEMP') or os.environ.get('TMP')
    if temp:
        candidates.append(Path(temp) / 'Venus' / 'logs')
    candidates.append(Path(__file__).resolve().parent.parent / 'logs')
    last_error = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return RotatingFileHandler(
                candidate / 'qq-service.log', maxBytes=512 * 1024,
                backupCount=3, encoding='utf-8')
        except OSError as exc:
            last_error = exc
    raise last_error


def run(start, folder):
    handler = open_status_handler(folder)
    handler.setFormatter(logging.Formatter('%(asctime)s [pid=%(process)d] %(message)s'))
    handler.addFilter(GatewayStatusOnly())
    logger = logging.Logger('venus.qq_service', level=logging.INFO)
    logger.addHandler(handler)
    sdk = logging.getLogger('botpy')
    propagate = sdk.propagate
    sdk.propagate = False
    sdk.addHandler(handler)
    try:
        logger.info('Venus QQ scheduled process started')
        try:
            status = start()
        except Exception as exc:
            logger.error('Venus QQ exited with %s', type(exc).__name__)
            return 1
        if status == 2:
            logger.error('Venus QQ configuration invalid; check local model and QQ settings')
            return 2
        # botpy may return normally after its session pool stops unexpectedly.
        logger.warning('Venus QQ returned unexpectedly; asking scheduler to restart')
        return 1
    finally:
        sdk.removeHandler(handler)
        sdk.propagate = propagate
        handler.close()


def _write_crash_note():
    """Persist the last startup failure where the console cannot show it.

    A scheduled ``pythonw`` process has no console and its stdout/stderr are
    redirected to the null device, so a failure before the status logger exists
    would otherwise be invisible. Only the exception traceback is written; no
    message text or credentials pass through this path.
    """
    import tempfile
    import traceback

    try:
        path = Path(tempfile.gettempdir()) / 'venus-crash.log'
        path.write_text(traceback.format_exc(), encoding='utf-8')
    except Exception:
        pass


def main():
    # A scheduled pythonw process has no console. Never capture raw SDK text.
    try:
        with open(os.devnull, 'w', encoding='utf-8') as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                root = Path(__file__).resolve().parent.parent
                os.chdir(root)
                folder = Path(os.environ['LOCALAPPDATA']) / 'Venus' / 'logs'

                def start():
                    from .qq_bot import main as start_qq

                    return start_qq(scheduled=True)

                return run(start, folder)
    except Exception:
        _write_crash_note()
        raise


if __name__ == '__main__':
    sys.exit(main())

