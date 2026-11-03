"""Listener ownership verification reused verbatim from PR #28."""

from .package import UnsafeOperation


def owns_listener(port, pid):
    """Never send the proxy secret to a different process on a reused local port."""
    import ctypes
    import socket
    import struct

    api = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
    api.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    api.restype = ctypes.c_uint32
    size = ctypes.c_uint32()
    if api(None, ctypes.byref(size), True, 2, 3, 0) not in (0, 122):
        raise UnsafeOperation("Não foi possível verificar o processo do backend.")
    buffer = ctypes.create_string_buffer(size.value)
    if api(buffer, ctypes.byref(size), True, 2, 3, 0):
        return False
    count = struct.unpack_from("<I", buffer.raw)[0]
    for index in range(count):
        row = struct.unpack_from("<6I", buffer.raw, 4 + index * 24)
        if row[0] == 2 and socket.ntohs(row[2] & 0xFFFF) == port and row[5] == pid:
            return True
    return False
