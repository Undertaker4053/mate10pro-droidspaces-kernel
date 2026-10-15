"""Replace only the kernel payload and its size/hash in the original v1 header."""
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path


def repack(header, kernel):
    h = bytearray(header)
    if h[:8] != b'ANDROID!' or struct.unpack_from('<I', h, 40)[0] != 1:
        raise ValueError('Expected Android boot header v1')
    page = struct.unpack_from('<I', h, 36)[0]
    if len(h) != page or any(struct.unpack_from('<I', h, p)[0] for p in (16, 24, 1632)):
        raise ValueError('Expected a kernel-only image with no recovery DTBO')
    if struct.unpack_from('<I', h, 1644)[0] != 1648:
        raise ValueError('Unexpected v1 header size')
    raw = gzip.decompress(kernel)
    if raw[56:60] != b'ARM\x64':
        raise ValueError('Kernel payload is not an ARM64 Image')
    struct.pack_into('<I', h, 8, len(kernel))
    digest = hashlib.sha1(kernel + struct.pack('<I', len(kernel)) + bytes(12)).digest()
    h[576:608] = digest + bytes(12)
    padding = bytes((-len(kernel)) % page)
    return bytes(h) + kernel + padding


if __name__ == '__main__':
    header, kernel, target = map(Path, sys.argv[1:4])
    output = repack(header.read_bytes(), kernel.read_bytes())
    target.write_bytes(output)
    digest = hashlib.sha256(output).hexdigest()
    target.with_suffix('.img.sha256').write_text(digest + '  ' + target.name + '\n')
    print(json.dumps({'image': target.name, 'bytes': len(output), 'sha256': digest}, indent=2))
