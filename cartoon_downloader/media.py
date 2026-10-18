"""Byte range parsing shared by the local media handler and its tests."""

import re


def byte_range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value.strip())
    if not match or size <= 0:
        raise ValueError('Unsatisfiable byte range')
    first, last = match.groups()
    if not first:
        if not last or int(last) <= 0:
            raise ValueError('Invalid suffix range')
        return max(0, size - int(last)), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError('Unsatisfiable byte range')
    return start, end
