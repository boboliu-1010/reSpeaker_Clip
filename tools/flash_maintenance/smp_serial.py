"""Bounded MCUboot SMP v1 serial client; no external flashing executable.

Framing follows Zephyr's SMP Transport Specification (127-byte lines, CRC16
0x1021/init=0). Only image list/upload and reset are implemented.
"""
import base64
import binascii
import hashlib
import struct
import time

import cbor2


def frames(packet):
    raw = struct.pack('!H', len(packet) + 2) + packet
    raw += struct.pack('!H', binascii.crc_hqx(packet, 0))
    for offset in range(0, len(raw), 93):
        yield (b'\x06\x09' if not offset else b'\x04\x14') + base64.b64encode(raw[offset:offset+93]) + b'\n'


class SMP:
    def __init__(self, serial_port, timeout=30):
        self.port, self.timeout, self.seq = serial_port, timeout, 0

    def request(self, group, command, body, write=False):
        self.seq = (self.seq + 1) & 255
        encoded = cbor2.dumps(body)
        op = 2 if write else 0
        packet = struct.pack('!BBHHBB', op, 0, len(encoded), group, self.seq, command) + encoded
        for line in frames(packet):
            if self.port.write(line) != len(line):
                raise IOError('Incomplete SMP serial write')
        self.port.flush()
        end, pending, expected = time.monotonic() + self.timeout, bytearray(), None
        while time.monotonic() < end:
            line = self.port.read_until(b'\n', 512)
            if not line.endswith(b'\n') or line[:2] not in (b'\x06\x09', b'\x04\x14'):
                continue
            try:
                data = base64.b64decode(line[2:-1], validate=True)
            except binascii.Error as error:
                raise ValueError('Invalid SMP base64 frame') from error
            if line[:2] == b'\x06\x09':
                if len(data) < 2:
                    raise ValueError('Missing SMP packet length')
                expected = int.from_bytes(data[:2], 'big')
                if not 10 <= expected <= 8192:
                    raise ValueError('Invalid SMP packet length')
                pending = bytearray(data[2:])
            elif expected is not None:
                pending.extend(data)
            else:
                continue
            if expected is None or len(pending) < expected:
                continue
            if len(pending) != expected or binascii.crc_hqx(pending, 0):
                raise ValueError('SMP response length/CRC mismatch')
            response, flags, length, got_group, seq, got_cmd = struct.unpack('!BBHHBB', pending[:8])
            if seq != self.seq:
                pending, expected = bytearray(), None
                continue
            if (response, flags, got_group, got_cmd) != (op + 1, 0, group, command) or length != expected - 10:
                raise ValueError('SMP response does not match request')
            result = cbor2.loads(pending[8:-2])
            if not isinstance(result, dict) or result.get('rc', 0) or result.get('err'):
                raise RuntimeError('Device rejected SMP request')
            return result
        raise TimeoutError('SMP response timeout; keep USB connected and resume')

    def images(self):
        value = self.request(1, 0, {}).get('images')
        if not isinstance(value, list):
            raise ValueError('Device did not return an image list')
        return value

    def upload(self, image, progress=lambda done, total: None):
        image_hash = hashlib.sha256(image).digest()
        offset, retries, exchanges = 0, 0, 0
        while offset < len(image):
            # Include CBOR/SMP overhead within a conservative 512-byte bootloader buffer.
            body = {'image': 0, 'off': offset, 'data': image[offset:offset+384]}
            if offset == 0:
                body.update(len=len(image), sha=image_hash)
            try:
                result = self.request(1, 1, body, write=True)
            except TimeoutError:
                retries += 1
                if retries > 3:
                    raise
                continue
            new_offset = result.get('off')
            if type(new_offset) is not int or not 0 <= new_offset <= len(image):
                raise ValueError('Invalid firmware upload offset')
            # A resumed first request may return a verified stored offset.
            if offset and new_offset > offset + len(body['data']):
                raise ValueError('Unexpected firmware upload offset jump')
            retries = retries + 1 if new_offset <= offset else 0
            exchanges += 1
            if retries > 3 or exchanges > (len(image)//384 + 1) * 4:
                raise TimeoutError('Firmware upload is not making progress')
            offset = new_offset
            progress(offset, len(image))

    def reset(self):
        return self.request(0, 5, {}, write=True)
