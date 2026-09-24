# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import os
import threading
import pytest
from tina4_python.dev_admin import _dev_read_bytes


def test_dev_file_descriptor_rejects_nonregular_and_oversized_files(tmp_path):
    good = tmp_path / 'good'; good.write_bytes(b'public')
    assert _dev_read_bytes(str(good), 6) == b'public'
    with pytest.raises(ValueError, match='File too large'):
        _dev_read_bytes(str(good), 5)
    link = tmp_path / 'link'; link.symlink_to(good)
    with pytest.raises(OSError):
        _dev_read_bytes(str(link), 20)
    fifo = tmp_path / 'fifo'; os.mkfifo(fifo)
    with pytest.raises(ValueError, match='Not a regular file'):
        _dev_read_bytes(str(fifo), 20)


def test_dev_file_descriptor_never_follows_a_concurrent_leaf_swap(tmp_path):
    target = tmp_path / 'public'; target.write_bytes(b'public')
    secret = tmp_path / '.env'; secret.write_bytes(b'synthetic-private')
    stop = threading.Event()
    def swap():
        next_file = tmp_path / 'next'
        while not stop.is_set():
            next_file.symlink_to(secret); os.replace(next_file, target)
            next_file.write_bytes(b'public'); os.replace(next_file, target)
    worker = threading.Thread(target=swap); worker.start()
    try:
        for _ in range(1000):
            try: data = _dev_read_bytes(str(target), 100)
            except OSError: continue
            assert data == b'public'
    finally:
        stop.set(); worker.join(timeout=5)
    assert not worker.is_alive()
