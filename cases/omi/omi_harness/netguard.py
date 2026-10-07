"""Outbound network is disabled inside the worker process.

The backbone runs in its own subprocess (halo.run.llm), and every service the run touches is
in-process, so no socket in this process may leave the machine. A chat tool that would call the web
(fetch_url, Perplexity, Gmail, Calendar) gets a connection error, which upstream turns into a tool
error string.
"""
import socket

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _local(address) -> bool:
    if not isinstance(address, tuple):          # unix-domain sockets
        return True
    return str(address[0]) in ('127.0.0.1', '::1', 'localhost')


def _connect(self, address):
    if _local(address):
        return _real_connect(self, address)
    raise ConnectionRefusedError(f'outbound network is disabled in this HALO run ({address[0]})')


def _connect_ex(self, address):
    if _local(address):
        return _real_connect_ex(self, address)
    return 111   # ECONNREFUSED


def install():
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
