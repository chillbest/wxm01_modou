"""Plain-text operational logs. Never log raw exceptions or request payloads."""
from datetime import datetime
from zoneinfo import ZoneInfo
import functools
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

_context = ContextVar("modou_log_context", default={})
logger = logging.getLogger("modou")
logger.addHandler(logging.NullHandler())


def clean(value):
    value = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in ("KEY", "TOKEN", "PASSWORD", "SECRET")) and len(secret) >= 4:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", "[URL]", value)
    value = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:api[_-]?key|token|password|secret|authorization)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    return value.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")


class SafeFormatter(logging.Formatter):
    def format(self, record):
        if hasattr(record, 'note_block'):
            return "\n\n" + "\n".join(clean(line) for line in record.note_block) + "\n\n"
        return clean(super().format(record))


def setup(directory=None, *, max_bytes=10 * 1024 * 1024, backups=5, started_at=None):
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parents[2] / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    for handler in list(logger.handlers):
        if getattr(handler, "_modou_owned", False):
            logger.removeHandler(handler)
            handler.close()
    started_at = started_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    day = started_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    formatter = SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for handler in (RotatingFileHandler(directory / f"modou_{day}.log", maxBytes=max_bytes, backupCount=backups, encoding="utf-8"), logging.StreamHandler()):
        handler._modou_owned = True
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@contextmanager
def context(**fields):
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def event(action, **fields):
    stats = _note_stats.get()
    if stats is not None and action == '条目最终结果':
        stats.results.append(fields['result'])
    data = {"run_id": "-", "job_id": "-", "note_id": "-", "batch_id": "-", "request_id": "-", **_context.get(), **fields}
    logger.info("%s %s", action, " ".join(f"{key}={clean(value)!r}" for key, value in data.items()))


def failure_reason(exc):
    from urllib.error import HTTPError, URLError
    if isinstance(exc, (TimeoutError,)) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return "请求超时"
    if isinstance(exc, HTTPError):
        return f"HTTP错误{exc.code}"
    if isinstance(exc, URLError):
        return "网络连接失败"
    return "响应无效或处理失败:" + type(exc).__name__


def logged_main(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        setup()
        started = time.monotonic()
        with context(run_id=uuid.uuid4().hex[:12], job_id=getattr(function.__globals__.get("__spec__"), "name", None) or function.__module__):
            event("运行开始")
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                if isinstance(exc, SystemExit) and exc.code in (0, None):
                    event("运行完成", elapsed_seconds=round(time.monotonic() - started, 3))
                else:
                    event("运行失败", reason=failure_reason(exc), elapsed_seconds=round(time.monotonic() - started, 3))
                raise
            event("运行完成", elapsed_seconds=round(time.monotonic() - started, 3))
            return result
    return wrapper


def stage(name, candidates=(), *, reason=None, result=None):
    candidates = list(candidates)
    event("识别阶段", stage=name, result=result or ("命中" if len(candidates) == 1 else "歧义" if candidates else "未命中"),
          reason=reason or ("唯一候选" if len(candidates) == 1 else "多个候选" if candidates else "无匹配候选"),
          candidates=[{k: c.get(k) for k in ("name_zh", "name_cn", "name", "gpc_id", "id") if c.get(k) is not None} for c in candidates])


def summary(statuses):
    statuses = list(statuses)
    event("笔记汇总", total=len(statuses), identified=statuses.count("已识别"), ambiguous=statuses.count("歧义"), unmatched=statuses.count("未识别"), review_status="待人工审核")


def logged_request(service):
    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with note_phase("联网识别"), context(request_id=uuid.uuid4().hex[:12]):
                started = time.monotonic()
                event("外部调用开始", service=service)
                try:
                    result = function(*args, **kwargs)
                except Exception as exc:
                    event("外部调用失败", service=service, reason=failure_reason(exc), elapsed_seconds=round(time.monotonic() - started, 3))
                    raise
                event("外部调用完成", service=service, elapsed_seconds=round(time.monotonic() - started, 3))
                return result
        return wrapper
    return decorate


@contextmanager
def logged_transaction(engine):
    with context(batch_id=uuid.uuid4().hex[:12]):
        event("导入事务开始", database="modou_test")
        try:
            with engine.begin() as conn:
                yield conn
        except Exception as exc:
            event("导入事务失败并回滚", reason=failure_reason(exc))
            raise
        event("导入事务已提交", database="modou_test")


_note_stats = ContextVar("modou_note_statistics", default=None)


class NoteStatistics:
    def __init__(self, path, *, shared=False):
        self.name = Path(path).name
        self.started_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        self.seconds = {key: 0.0 for key in ('读取/规则', '本地查询', '联网识别', '输出')}
        self.results = []
        self.total = None
        self.shared = shared
        self.current = '读取/规则'
        self.tick = time.monotonic()
        self.failed_phase = None
        self.failed_error = None

    def charge(self):
        now = time.monotonic()
        self.seconds[self.current] += now - self.tick
        self.tick = now

    def emit(self, error=None):
        counts = [self.results.count(k) for k in ('已识别', '歧义', '未识别')]
        total = self.total
        remaining = str(max(0, total - len(self.results))) if total is not None else '未知'
        title = f"笔记统计｜《{self.name}》｜开始{self.started_at:%Y-%m-%d %H:%M:%S}｜"
        title += ('失败：' + (self.failed_phase if error is self.failed_error else self.current) + '/' + failure_reason(error)) if error else '成功'
        title += f"｜总耗时{sum(self.seconds.values()):.2f}秒"
        title += f"｜运行{_context.get().get('run_id', '-')}"
        if self.shared:
            title += '｜共享准备耗时另计'
        lines = [title,
                 f"条目{total if total is not None else '未知'}｜已识别{counts[0]}｜歧义{counts[1]}｜未识别{counts[2]}｜未处理{remaining}｜" + ('已处理结果待人工审核' if error else '全部待人工审核'),
                 '耗时：' + '｜'.join(f'{k}{v:.2f}秒' for k, v in self.seconds.items())]
        logger.info('笔记统计', extra={'note_block': lines})


@contextmanager
def note_statistics(path, *, shared=False, enabled=True, existing=None):
    if not enabled:
        yield None
        return
    stats = existing or NoteStatistics(path, shared=shared)
    stats.tick = time.monotonic()
    token = _note_stats.set(stats)
    error = None
    try:
        with context(note_id=str(path)):
            yield stats
    except BaseException as exc:
        error = exc
        raise
    finally:
        stats.charge()
        stats.emit(error)
        _note_stats.reset(token)


@contextmanager
def note_phase(name):
    stats = _note_stats.get()
    if stats is None:
        yield
        return
    stats.charge()
    previous = stats.current
    stats.current = name
    try:
        yield
    except BaseException as exc:
        if stats.failed_error is not exc:
            stats.failed_phase = name
            stats.failed_error = exc
        raise
    finally:
        stats.charge()
        stats.current = previous


def note_total(total):
    stats = _note_stats.get()
    if stats is not None:
        stats.total = total
