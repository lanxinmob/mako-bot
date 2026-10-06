"""Run the actual deletion script against a disposable local Redis process."""
import shutil
import socket
import subprocess
import sys
import time

import pytest
import redis

from src.services.autonomy.repository import DELETE_PENDING, CREATE_PENDING


@pytest.fixture
def isolated_redis(tmp_path):
    executable = shutil.which("redis-server")
    if not executable:
        pytest.skip("isolated Redis executable unavailable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [executable, "--bind", "127.0.0.1", "--port", str(port),
         "--save", "", "--appendonly", "no"],
        cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True,
                         socket_connect_timeout=.2, socket_timeout=.5)
    try:
        deadline = time.monotonic() + 5
        while True:
            if process.poll() is not None:
                pytest.fail("isolated Redis process exited during startup")
            try:
                # Verify the process identity before performing any writes.
                if client.info("server")["process_id"] == process.pid:
                    break
                pytest.fail("Redis port belongs to another process")
            except redis.ConnectionError:
                if time.monotonic() >= deadline:
                    pytest.fail("isolated Redis startup timed out")
                time.sleep(.05)
        yield client
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("latest", ["old", "new"])
def test_delete_pending_preserves_new_latest(isolated_redis, latest):
    client = isolated_redis
    client.set("autonomy:pending:old", "old payload")
    client.set("autonomy:pending:new", "new payload")
    client.set("autonomy:pending:latest", latest)
    assert client.eval(DELETE_PENDING, 2, "autonomy:pending:old",
                       "autonomy:pending:latest", "old") == 1
    assert client.get("autonomy:pending:old") is None
    assert client.get("autonomy:pending:new") == "new payload"
    assert client.get("autonomy:pending:latest") == ("new" if latest == "new" else None)


@pytest.mark.parametrize("collision", ["pending", "execution", None])
def test_create_pending_never_overwrites_existing_action(isolated_redis, collision):
    client = isolated_redis
    client.set("autonomy:pending:latest", "previous")
    if collision:
        client.set(f"autonomy:{collision}:p1", "existing")
    result = client.eval(CREATE_PENDING, 3, "autonomy:pending:p1",
                         "autonomy:pending:latest", "autonomy:execution:p1",
                         "new payload", "p1", 300)
    assert result == int(collision is None)
    if collision:
        assert client.get(f"autonomy:{collision}:p1") == "existing"
        assert client.get("autonomy:pending:latest") == "previous"
    else:
        assert client.get("autonomy:pending:p1") == "new payload"
        assert client.get("autonomy:pending:latest") == "p1"
        assert 0 < client.ttl("autonomy:pending:p1") <= 300
