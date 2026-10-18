"""Cancellation of external tool process trees."""

import os
import subprocess
import time


def terminate_process(proc):
    if not proc or proc.poll() is not None:
        return
    if os.name == 'nt':
        try:
            result = subprocess.run(
                ['taskkill.exe', '/PID', str(proc.pid), '/T', '/F'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=5,
            )
            if result.returncode != 0 and proc.poll() is None:
                raise OSError(result.stderr.decode(errors='replace'))
            proc.wait(timeout=2)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait(timeout=4)


def run_cancellable(cmd, *, timeout, cancel_check=None, **kwargs):
    """Drain both pipes while checking cancellation, including during search."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel_check:
                cancel_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                stdout, stderr = proc.communicate(timeout=min(.25, remaining))
                return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        try:
            if proc.poll() is None:
                terminate_process(proc)
        finally:
            proc.communicate()
