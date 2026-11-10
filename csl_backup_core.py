"""Private state, coherent captures and bounded container preflight for backups."""

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid
import zipfile

from csl_canonical import strict_json
from csl_transfer import TransferError

NORMAL_CONTAINER = 64 * 1024**2
MAX_OBJECT = 256 * 1024**2
MAX_MANIFEST = 16 * 1024**2
MAX_MEMBERS = 10000
MAX_RATIO = 200
NAMESPACE = uuid.UUID("e13079ba-d83d-5bb6-ae72-c436da9c98d6")


class BackupBusy(TransferError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    def check(item):
        if isinstance(item, dict):
            if not all(isinstance(k, str) for k in item):
                raise TransferError("Non-string backup JSON key")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, int, bool):
            raise TransferError("Unsupported backup canonical value")
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def hash_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def exclusive_output(target, *, source=None):
    """Only clean owned staging; preexisting/racing final paths are never touched."""
    target = Path(target)
    if (os.path.lexists(target) or source is not None and
            Path(source).resolve() == target.resolve()):
        raise TransferError("Refusing existing, symlinked or aliased output")
    with tempfile.TemporaryDirectory(prefix=".csl-output-", dir=target.parent) as directory:
        staging = Path(directory) / "output"
        yield staging
        if not staging.is_file() or staging.is_symlink():
            raise TransferError("No regular owned output to publish")
        staging.chmod(0o600)
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())
        try:
            os.link(staging, target)
        except FileExistsError:
            raise TransferError("Output appeared concurrently; existing file unchanged") from None
        fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def uid(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise TransferError("Invalid backup UUID") from None
    return value


def source_kind(value):
    """Codex 0.167 SessionSource, including structured SubAgent serialization."""
    if isinstance(value, str) and value in ("cli", "vscode", "exec"):
        return "agent" if value == "exec" else "interactive"
    if isinstance(value, dict) and set(value) == {"subagent"}:
        child = value["subagent"]
        if child in ("review", "compact", "memory_consolidation"):
            return "agent"
        if isinstance(child, dict) and set(child) == {"thread_spawn"}:
            spawn = child["thread_spawn"]
            if (isinstance(spawn, dict) and isinstance(spawn.get("parent_thread_id"), str) and
                    type(spawn.get("depth")) is int and spawn["depth"] >= 0):
                uid(spawn["parent_thread_id"])
                return "agent"
        if isinstance(child, dict) and set(child) == {"other"} and isinstance(child["other"], str):
            return "agent"
    if isinstance(value, dict) and set(value) == {"internal"} and value["internal"] in ("guardian", "memory_consolidation"):
        return "agent"
    if isinstance(value, dict) and set(value) == {"custom"} and isinstance(value["custom"], str):
        return "noninteractive"
    if value in ("app_server", "mcp", "unknown"):
        return "noninteractive"
    raise TransferError("Unknown Codex SessionSource; not converted to cli")


def json_read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TransferError("Duplicate backup JSON field")
            result[key] = value
        return result
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_MANIFEST + 1)
        if len(raw) > MAX_MANIFEST:
            raise TransferError("Backup JSON exceeds limit")
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(TransferError("Invalid JSON constant")))
    except (ValueError, UnicodeError):
        raise TransferError("Invalid backup JSON") from None


def save(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise TransferError("Refusing symlinked backup state directory")
    path.parent.chmod(0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            if exclusive:
                os.link(temporary, path)
            else:
                if path.is_symlink():
                    raise TransferError("Refusing symlinked state file")
                os.replace(temporary, path)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked(root):
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    fd = os.open(root / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupBusy("Backup busy; another local operation owns the lock") from None
        yield
    finally:
        os.close(fd)


def capture(source, destination):
    """Exact complete-line prefix; appends deferred, rewrite/truncate rejected."""
    with exclusive_output(destination, source=source) as staging:
        result = _capture_to(source, staging)
    return result


def _capture_to(source, destination):
    source, destination = Path(source), Path(destination)
    for attempt in range(3):
        cut_at = now()
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_OBJECT:
                raise TransferError("Unsupported native history size/type")
            remaining = before.st_size
            digest = hashlib.sha256()
            metadata, messages = [], 0
            with os.fdopen(os.dup(fd), "rb") as stream, destination.open("wb") as target:
                destination.chmod(0o600)
                while remaining:
                    line = stream.readline(remaining)
                    remaining -= len(line)
                    if not line:
                        break
                    if not line.strip():
                        digest.update(line)
                        target.write(line)
                        continue
                    try:
                        record = strict_json(line)
                    except (ValueError, UnicodeError):
                        if not line.endswith(b"\n"):
                            break  # Only an incomplete tail is deferred, never a malformed complete row.
                        raise TransferError("Malformed native JSONL; not silently skipped") from None
                    if (not isinstance(record, dict) or record.get("type") not in
                            ("session_meta", "response_item", "event_msg", "turn_context", "compacted") or
                            not isinstance(record.get("payload"), dict)):
                        raise TransferError("Unknown native record; capture rejected, source unchanged")
                    payload = record["payload"]
                    if record["type"] == "session_meta":
                        metadata.append(payload)
                    messages += int(payload.get("type") == "message" or payload.get("type") in ("user_message", "agent_message"))
                    digest.update(line)
                    target.write(line)
                target.flush()
                os.fsync(target.fileno())
            size = destination.stat().st_size
            after = os.fstat(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            check = hashlib.sha256()
            checked = 0
            while checked < size:
                block = os.read(fd, min(1024**2, size - checked))
                if not block:
                    break
                checked += len(block)
                check.update(block)
            current = source.stat(follow_symlinks=False)
            if ((before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or
                    after.st_size < before.st_size or checked != size or check.digest() != digest.digest()):
                if attempt < 2:
                    continue
                raise TransferError("Source changed during capture; bounded retries exhausted")
            if not metadata or len({uid(m.get("id")) for m in metadata}) != 1:
                raise TransferError("Missing or inconsistent source session identity")
            return {"source_uuid": metadata[-1]["id"], "bytes": size, "sha256": digest.hexdigest(),
                    "captured_at": cut_at, "last_observed_at": now(), "observed_size": before.st_size,
                    "deferred_bytes": max(0, after.st_size - size), "metadata": metadata[-1],
                    "message_records": messages}
        finally:
            os.close(fd)


def zip_preflight(archive):
    """Check every declared size/path/type/ratio BEFORE reading any member."""
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if not infos or len(infos) > MAX_MEMBERS + 1 or len(set(names)) != len(names) or "manifest.json" not in names:
        raise TransferError("Missing/duplicate/too many container members")
    total = 0
    for info in infos:
        if (info.filename != "manifest.json" and not re.fullmatch(r"members/[0-9a-f-]{36}\.jsonl", info.filename) or
                stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.flag_bits & 1 or
                info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise TransferError("Unsafe container member")
        limit = MAX_MANIFEST if info.filename == "manifest.json" else MAX_OBJECT
        if not 0 < info.file_size <= limit or info.file_size > max(1, info.compress_size) * MAX_RATIO:
            raise TransferError("Oversize or excessive-ratio ZIP member")
        total += info.file_size
        if total > MAX_OBJECT:
            raise TransferError("Container uncompressed total exceeds limit")
    return infos


def zip_read(archive, name):
    info = archive.getinfo(name)
    with archive.open(info) as stream:
        data = stream.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise TransferError("Container member differs from declared size")
    return data


def header_source(source):
    """Bounded, coherent header classification before copying an excluded source.

    This does not claim capture/integrity evidence for excluded conversations.
    Unusual headers fall back to full capture and validation.
    """
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise TransferError("Unsupported native source type")
        with os.fdopen(os.dup(fd), 'rb') as stream:
            line = stream.readline(1024**2 + 1)
        if len(line) > 1024**2:
            return None
        try:
            row = strict_json(line)
        except (ValueError, UnicodeError):
            return None
        after = os.fstat(fd)
        current = Path(source).stat(follow_symlinks=False)
        fields = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if fields(before) != fields(after) or fields(after) != fields(current):
            return None
        if not isinstance(row, dict) or row.get('type') != 'session_meta' or not isinstance(row.get('payload'), dict):
            return None
        uid(row['payload'].get('id'))
        source_kind(row['payload'].get('source', 'cli'))
        return row['payload']
    finally:
        os.close(fd)


def zip_digest(archive, entry, target=None):
    """Preflight must precede this bounded streaming member read."""
    digest, count = hashlib.sha256(), 0
    with archive.open(entry['file']) as source:
        while chunk := source.read(1024**2):
            count += len(chunk)
            if count > entry['bytes']:
                raise TransferError("Member exceeds declared size")
            digest.update(chunk)
            if target is not None:
                target.write(chunk)
    if count != entry['bytes'] or digest.hexdigest() != entry['sha256']:
        raise TransferError("Member checksum/size differs")
    return digest.hexdigest()


def zip_extract(archive, entry, destination):
    with exclusive_output(destination) as staging:
        with staging.open('xb') as target:
            zip_digest(archive, entry, target)
