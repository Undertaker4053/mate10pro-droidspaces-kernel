"""Validate the kernel-only Android image container; no runtime claim."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys


def verify(header, image):
    assert header[:8] == b'ANDROID!'
    assert struct.unpack_from('<I', header, 40)[0] == 1
    page = struct.unpack_from('<I', header, 36)[0]
    assert page == len(header) == 2048
    assert len(image) <= 24 * 1024 * 1024, 'Exceeds known 24 MiB kernel partition'
    assert len(image) % page == 0
    size = struct.unpack_from('<I', image, 8)[0]
    assert len(image) == page + (size + page - 1) // page * page
    allowed = set(range(8, 12)) | set(range(576, 608))
    assert all(image[i] == b for i, b in enumerate(header) if i not in allowed)
    payload = image[page:page + size]
    assert payload[:2] == b'\x1f\x8b'
    assert not any(image[page + size:]), 'Nonzero image padding'
    digest = hashlib.sha1(payload + struct.pack('<I', size) + bytes(12)).digest()
    assert image[576:608] == digest + bytes(12), 'Android boot payload hash mismatch'
    raw = gzip.decompress(payload)
    assert raw[56:60] == b'ARM\x64'
    # image_size includes the NOBITS/BSS area, which is absent from Image.
    memory_size = struct.unpack_from('<Q', raw, 16)[0]
    assert memory_size >= len(raw), 'ARM64 memory extent is smaller than Image'
    assert b'Linux version 4.9.148-BLA_EMUI9.1_KernelSU_DSfullC ' in raw
    return {'passed': True, 'hardware_tested': False,
            'image_bytes': len(image), 'kernel_gzip_bytes': size,
            'arm64_image_bytes': len(raw), 'arm64_memory_bytes': memory_size,
            'partition_bytes': 24 * 1024 * 1024,
            'sha256': hashlib.sha256(image).hexdigest(),
            'header_preserved_except_kernel_size_and_hash': True}


if __name__ == '__main__':
    header, image, output = map(Path, sys.argv[1:])
    report = verify(header.read_bytes(), image.read_bytes())
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
