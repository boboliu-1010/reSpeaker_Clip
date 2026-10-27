import base64
import binascii
from contextlib import redirect_stdout, nullcontext
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from littlefs import LittleFS, UserContext

from build_macos import assemble
from firmware_package import Bundle, verify_image
from flash_tool import START, END, ERASE, load_backup
from flash_tool import Device
from migrate import GEOMETRY
from smp_serial import SMP, frames
from upgrade import Journal, MacUSB, execute, main


def signed(key, text):
    header = bytearray(32)
    struct.pack_into('<IIHHII', header, 0, 0x96f3b83d, 0, 32, 0, len(text), 0)
    payload = bytes(header) + text
    pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
    signature = key.sign(payload, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    tlvs = b''.join(struct.pack('<BBH', kind, 0, len(value))+value for kind, value in (
        (1, hashlib.sha256(pub).digest()), (0x10, hashlib.sha256(payload).digest()), (0x20, signature)))
    return payload + struct.pack('<HH', 0x6907, len(tlvs)+4) + tlvs


class PackageTests(unittest.TestCase):
    def test_signed_images_corruption_wrong_key_and_bundle_tampering(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        image = signed(key, b'firmware')
        self.assertEqual(len(verify_image(image, pem)), 64)
        with self.assertRaises(ValueError):
            verify_image(image[:32] + b'X' + image[33:], pem)
        with self.assertRaises(ValueError):
            verify_image(image+b'garbage', pem)
        with self.assertRaises(InvalidSignature):
            verify_image(image[:-1]+bytes([image[-1]^1]),pem)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        with self.assertRaises(ValueError):
            verify_image(image, other.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for role in ('maintenance', 'firmware', 'rollback'):
                files[role] = root/(role+'.bin'); files[role].write_bytes(signed(key, role.encode()))
            files['public_key'] = root/'public.pem';files['public_key'].write_bytes(pem)
            files['patch'] = root/'patch.bin'; files['patch'].write_bytes(b'P'*87046)
            config = root/'config';config.write_text('CONFIG_CLIP_UPLOAD=y\nCONFIG_NRF_WIFI_PATCHES_EXT_FLASH_STORE=y\n')
            with patch('firmware_package.PATCH_SHA256', hashlib.sha256(files['patch'].read_bytes()).hexdigest()):
                assemble(root/'bundle', files, config)
                with patch('upgrade.MacUSB') as hardware, redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['inspect','--bundle',str(root/'bundle')]),0)
                    hardware.assert_not_called()
                (root/'bundle/firmware.signed.bin').write_bytes(b'invalid')
                with self.assertRaises(ValueError):Bundle(root/'bundle')


class Wire:
    def __init__(self, transform=None):
        self.incoming, self.raw, self.length = [], bytearray(), None
        self.transform = transform
        self.uploaded = bytearray()

    def write(self, line):
        data = base64.b64decode(line[2:-1])
        if line[:2] == b'\x06\x09':
            self.length = int.from_bytes(data[:2], 'big'); self.raw = bytearray(data[2:])
        else:self.raw.extend(data)
        if len(self.raw) == self.length:
            assert binascii.crc_hqx(self.raw,0)==0
            op, flags, length, group, seq, command = struct.unpack('!BBHHBB',self.raw[:8])
            body = cbor2.loads(self.raw[8:-2])
            if command == 1:
                off=body['off'];self.uploaded[off:off+len(body['data'])]=body['data']
                reply={'off':off+len(body['data'])}
            else:reply={'images':[{'slot':0,'hash':b'x'*32,'version':'0'*180}]}
            payload=cbor2.dumps(reply)
            packet=struct.pack('!BBHHBB',op+1,flags,len(payload),group,seq,command)+payload
            values=list(frames(packet))
            self.incoming.extend(self.transform(values) if self.transform else values)
        return len(line)

    def flush(self):pass
    def read_until(self,*args):return self.incoming.pop(0) if self.incoming else b''


class SMPTests(unittest.TestCase):
    def test_wrong_normal_port_probe_closes_its_serial_handle(self):
        with patch('serial.Serial') as port, patch.object(Device,'identify',side_effect=ValueError('not maintenance')):
            with self.assertRaises(ValueError):Device('fake-port')
            port.return_value.close.assert_called_once()

    def test_real_framing_crc_and_multichunk_upload(self):
        data=bytes(range(256))*12
        wire=Wire();smp=SMP(wire,.05)
        smp.upload(data)
        self.assertEqual(wire.uploaded,data)
        self.assertEqual(smp.images()[0]['slot'],0)
        self.assertTrue(all(len(x)<=127 for x in frames(data)))

    def test_corrupt_crc_and_nonprogress_are_rejected(self):
        def corrupt(lines):
            raw=bytearray(base64.b64decode(lines[-1][2:-1]));raw[-1]^=1
            return [*lines[:-1],lines[-1][:2]+base64.b64encode(raw)+b'\n']
        with self.assertRaises(ValueError):SMP(Wire(corrupt),.05).images()
        smp=SMP(Wire(),.05)
        with patch.object(smp,'request',return_value={'off':0}):
            with self.assertRaises(TimeoutError):smp.upload(b'file')


class FakeMaintenance:
    def __init__(self, data):
        self.data=bytearray(data);self.info={'device_id':'synthetic'}
        self.fail_write=False;self.writes=0
    def region(self):return bytes(self.data)
    def close(self):pass
    def command(self,text):
        if text.startswith('ARM '):return 'OK ARM'
        op,offset,length=text.split();offset=int(offset,16);length=int(length,16)
        assert op=='ERASE' and offset>=START and length==ERASE
        self.data[offset-START:offset-START+length]=b'\xff'*length
        return 'OK ERASE'
    def write(self,offset,payload):
        self.data[offset-START:offset-START+len(payload)]=payload;self.writes+=1
        if self.fail_write:raise IOError('simulated USB interruption')


class FakeMac:
    def __init__(self,maintenance,journal):
        self.device,self.journal=maintenance,journal;self.installs=[];self.fail_install=False
    def identify(self):self.journal.save(usb_serial='synthetic-usb')
    def maintenance(self,first=False):return self.device
    def install(self,role):
        self.installs.append(role)
        if self.fail_install:raise IOError('simulated image upload interruption')
    def verify_boot(self):return {'version_query_passed':True}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        fs=LittleFS(context=UserContext(buffer=bytearray(b'\xff'*(END-START))),block_count=109,**GEOMETRY)
        fs.makedirs('/settings',exist_ok=True)
        with fs.open('/settings/run','wb') as output:output.write(b'synthetic private settings')
        fs.setattr('/settings',7,b'attribute');fs.unmount()
        self.original=bytes(fs.context.buffer)
        patch_bytes=b'P'*87046
        (self.root/'nrf70.bin').write_bytes(patch_bytes)
        self.bundle=SimpleNamespace(root=self.root,assets={'patch':patch_bytes},
            manifest={'files':{'patch':{'file':'nrf70.bin'}}})
        self.journal=Journal(self.root/'run','bundle-fingerprint')
        self.maintenance=FakeMaintenance(self.original)
        self.mac=FakeMac(self.maintenance,self.journal)
        self.pin=patch('migrate.PATCH_SHA256',hashlib.sha256(patch_bytes).hexdigest())
        self.pin.start();self.addCleanup(self.pin.stop)
        self.output=redirect_stdout(io.StringIO());self.output.__enter__();self.addCleanup(self.output.__exit__,None,None,None)

    def run_flow(self,restore=False):execute(self.bundle,self.journal,self.mac,restore)

    def test_whole_flow_keeps_backup_and_completed_resume_is_noop(self):
        self.run_flow()
        self.assertEqual(self.journal.data['phase'],'complete')
        self.assertEqual(load_backup(self.journal.path('backup_dir'))[1],self.original)
        self.assertEqual(self.mac.installs,['firmware'])
        self.assertEqual((self.journal.root/'state.json').stat().st_mode&0o777,0o600)
        self.run_flow();self.assertEqual(self.mac.installs,['firmware'])

    def test_partial_write_cannot_be_resumed_as_new_backup_and_restore_works(self):
        self.maintenance.fail_write=True
        with self.assertRaises(IOError):self.run_flow()
        self.assertEqual(self.journal.data['phase'],'apply_started')
        backup_path=self.journal.path('backup_dir')
        self.maintenance.fail_write=False
        writes=self.maintenance.writes
        with self.assertRaisesRegex(ValueError,'partly changed'):self.run_flow()
        self.assertEqual(writes,self.maintenance.writes)
        self.assertEqual(backup_path,self.journal.path('backup_dir'))
        self.run_flow(restore=True)
        self.assertEqual(self.maintenance.region(),self.original)
        self.assertEqual(self.mac.installs,['rollback'])
        self.assertEqual(self.journal.data['phase'],'restored')

    def test_resume_after_final_install_failure_rechecks_without_reapplying(self):
        self.mac.fail_install=True
        with self.assertRaises(IOError):self.run_flow()
        self.assertEqual(self.journal.data['phase'],'target_installing')
        writes=self.maintenance.writes;self.mac.fail_install=False
        self.run_flow()
        self.assertEqual(self.maintenance.writes,writes)
        self.assertEqual(self.journal.data['phase'],'complete')

    def test_wrong_device_and_changed_bundle_are_rejected(self):
        self.journal.save(device={'device_id':'another'})
        with self.assertRaisesRegex(ValueError,'differs'):self.run_flow()
        self.assertEqual(self.maintenance.writes,0)

        with self.assertRaises(ValueError):Journal(self.journal.root,'other-bundle')

    def test_process_lock_blocks_second_writer(self):
        with self.journal.lock():
            with self.assertRaises(BlockingIOError):
                with Journal(self.journal.root,'bundle-fingerprint').lock():pass

    def test_failed_readonly_backup_can_return_to_original_application(self):
        self.journal.save(phase='backup_running',backup_dir='incomplete-backup')
        self.run_flow(restore=True)
        self.assertEqual(self.mac.installs,['rollback'])
        self.assertEqual(self.maintenance.region(),self.original)
        self.assertEqual(self.journal.data['phase'],'restored')

    def test_missing_original_backup_after_write_is_never_recreated(self):
        self.journal.save(phase='apply_started',backup_dir='missing')
        with self.assertRaisesRegex(ValueError,'backup'):self.run_flow(restore=True)
        self.assertEqual(self.mac.installs,[])
        self.assertEqual(self.maintenance.writes,0)


class BackendTests(unittest.TestCase):
    def test_unknown_factory_hash_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(Path(directory)/'run','bundle')
            bundle=SimpleNamespace(images={'maintenance':'11'*32,'firmware':'22'*32,'rollback':'33'*32},
                                   assets={'maintenance':b'image'})
            mac=MacUSB(bundle,journal)
            client=SimpleNamespace(images=lambda:[{'slot':0,'hash':b'X'*32}])
            with patch.object(mac,'recovery',return_value=nullcontext(client)):
                with self.assertRaisesRegex(ValueError,'supported bundle image'):mac.install('maintenance',first=True)
            self.assertNotIn('installing',journal.data)

    def test_partial_primary_can_be_replaced_only_on_resume_and_verified_before_reset(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            journal=Journal(Path(directory)/'run','bundle')
            bundle=SimpleNamespace(images={'maintenance':'11'*32,'firmware':'22'*32,'rollback':'33'*32},
                                   assets={'maintenance':b'image'})
            mac=MacUSB(bundle,journal)
            state={'hash':b'', 'reset':False}
            def upload(data,progress):state['hash']=bytes.fromhex(bundle.images['maintenance'])
            client=SimpleNamespace(images=lambda:[{'slot':0,'hash':state['hash']}],upload=upload,
                                   reset=lambda:state.update(reset=True))
            with patch.object(mac,'recovery',return_value=nullcontext(client)):
                with self.assertRaises(ValueError):mac.install('maintenance',first=True)
                mac.install('maintenance',first=False)
            self.assertTrue(state['reset'])
            self.assertEqual(journal.data['primary_hash'],'11'*32)
