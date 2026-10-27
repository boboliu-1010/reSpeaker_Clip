"""Mac USB migration/upgrade coordinator. No SDK, nrfutil or network required.

An interrupted filesystem write is never treated as a new source filesystem.
Resume verifies its exact contents; partial migration requires explicit restore.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import uuid

import serial
from serial.tools import list_ports

from firmware_package import Bundle
from flash_tool import Device, END, START, apply_image, backup, load_backup, private_write, sha
from migrate import prepare
from smp_serial import SMP


def say(message):
    print(message, flush=True)


@contextmanager
def prevent_sleep():
    process = subprocess.Popen(['/usr/bin/caffeinate', '-ims', '-w', str(os.getpid())],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        process.terminate()
        process.wait()


class Journal:
    def __init__(self, root, fingerprint):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        path = self.root/'state.json'
        self.data = json.loads(path.read_text()) if path.exists() else {'phase': 'new', 'bundle': fingerprint}
        if self.data.get('bundle') != fingerprint:
            raise ValueError('This run belongs to a different bundle; use the original bundle')

    @contextmanager
    def lock(self):
        with os.fdopen(os.open(self.root/'run.lock', os.O_CREAT | os.O_RDWR, 0o600), 'w') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def save(self, **values):
        self.data.update(values)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.root, delete=False) as out:
            json.dump(self.data, out, indent=2)
            out.write('\n'); out.flush(); os.fsync(out.fileno())
            temporary = out.name
        os.replace(temporary, self.root/'state.json')
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        event = {'time': time.time(), 'phase': self.data['phase']}
        for key in ('installing', 'primary_hash', 'backup_dir', 'migration_dir'):
            if key in values:
                event[key] = values[key]
        with os.fdopen(os.open(self.root/'events.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600), 'a') as out:
            out.write(json.dumps(event)+'\n'); out.flush(); os.fsync(out.fileno())

    def path(self, key):
        path = self.root/self.data[key]
        if path.resolve().parent != self.root or path.is_symlink():
            raise ValueError('Invalid run record path')
        return path


class MacUSB:
    def __init__(self, bundle, journal, usb_serial=None, timeout=120):
        self.bundle, self.journal, self.timeout = bundle, journal, timeout
        self.usb_serial = journal.data.get('usb_serial') or usb_serial
        if usb_serial and self.usb_serial != usb_serial:
            raise ValueError('USB identity differs from the recorded device')

    def ports(self, pid=None):
        return [p for p in list_ports.comports() if p.vid == 0x2886 and p.pid in (0x0069, 0x8069)
                and (pid is None or p.pid == pid)
                and (not self.usb_serial or p.serial_number == self.usb_serial)]

    def identify(self):
        ports = self.ports()
        identities = {p.serial_number for p in ports}
        if not identities or None in identities or len(identities) != 1:
            raise RuntimeError('Connect exactly one Clip with USB data enabled, or enter Recovery; multiple devices require --usb-serial')
        self.usb_serial = identities.pop()
        self.journal.save(usb_serial=self.usb_serial)

    @contextmanager
    def recovery(self, trigger=True):
        if trigger and not self.ports(0x8069):
            ports = self.ports(0x0069)
            if len(ports) == 1:
                try:
                    with serial.Serial(ports[0].device, 1200, timeout=1) as channel:
                        channel.dtr = False
                except serial.SerialException:
                    pass  # A reset can remove the port before close completes.
        say('等待同一台设备的 Recovery 串口；必要时按住按键并接入 USB，直到显示 Recovery Mode。')
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            for port in self.ports(0x8069):
                channel = None
                try:
                    channel = serial.Serial(port.device, 115200, timeout=.2, write_timeout=5, exclusive=True)
                    client = SMP(channel, timeout=2)
                    client.images()
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    if channel is not None:
                        channel.close()
                    continue
                client.timeout = 30
                try:
                    yield client
                finally:
                    channel.close()
                return
            time.sleep(.5)
        raise TimeoutError('Recovery not detected; keep USB connected and resume')

    def install(self, role, first=False):
        with self.recovery(trigger=not first) as client:
            active = [x for x in client.images() if x.get('image', 0) == 0 and x.get('slot') == 0]
            raw_hash = active[0].get('hash') if active else None
            current = raw_hash.hex() if isinstance(raw_hash, bytes) and len(raw_hash) == 32 else None
            allowed = set(self.bundle.images.values())
            if current not in allowed and not (current is None and not first):
                raise ValueError('Installed application is not a supported bundle image; do not migrate an unknown factory version')
            if first and current != self.bundle.images['rollback']:
                raise ValueError('Factory image does not match this bundle rollback image')
            self.journal.save(installing=role)
            last_percent = -1

            def progress(done, total):
                nonlocal last_percent
                percent = done * 100 // total
                if percent != last_percent and (percent % 5 == 0 or done == total):
                    say(f'{role}: {percent}%')
                    last_percent = percent

            client.upload(self.bundle.assets[role], progress)
            expected = bytes.fromhex(self.bundle.images[role])
            if not any(x.get('image', 0) == 0 and x.get('slot') == 0 and x.get('hash') == expected for x in client.images()):
                raise ValueError('Recovery image hash differs after upload; do not continue')
            self.journal.save(primary_hash=self.bundle.images[role])
            try:
                client.reset()
            except (TimeoutError, serial.SerialException):
                pass  # The next mode probe must prove whether the reset worked.

    def maintenance(self, first=False):
        if not first:
            for port in self.ports(0x0069):
                try:
                    return Device(port.device)
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    continue
        say('安装维护固件（只更新应用核，保留 Bootloader 和网络核）')
        self.install('maintenance', first=first)
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            for port in self.ports(0x0069):
                try:
                    return Device(port.device)
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    continue
            time.sleep(.5)
        raise TimeoutError('Maintenance application did not respond; resume via USB Recovery')

    def verify_boot(self):
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            for port in self.ports(0x0069):
                try:
                    with serial.Serial(port.device, 115200, timeout=.2, write_timeout=5, exclusive=True) as channel:
                        channel.write(b'AT+VERSION\r\n')
                        reply_end = min(end, time.monotonic() + 3)
                        while time.monotonic() < reply_end:
                            line = channel.read_until(b'\n', 4096).strip()
                            try:
                                value = json.loads(line)
                            except (ValueError, UnicodeError):
                                continue
                            if isinstance(value, dict) and value.get('ok') is True:
                                return {'version_query_passed': True}
                except (OSError, TimeoutError):
                    continue
            time.sleep(.5)
        raise TimeoutError('New application did not answer VERSION; resume or restore through Recovery')


def execute(bundle, journal, device, restore=False):
    """Backend injection allows whole-flow fault tests without USB access."""
    if journal.data['phase'] == 'complete' and not restore:
        say('本次升级已完成；未重复操作设备。')
        return
    device.identify()
    if restore:
        try:
            load_backup(journal.path('backup_dir'))
        except (OSError, ValueError, KeyError):
            if journal.data['phase'] not in ('maintenance_installing', 'backup_running', 'backup_verified'):
                raise ValueError('No verified original backup is available; refuse restore after possible Flash writes')
            # The write-ahead phase proves this tool has not started any external
            # erase/write. A failed read-only backup must not strand the user.
            say('尚未开始写外置 Flash，仅重新安装原布局回退固件。')
            device.install('rollback')
            journal.save(phase='restored', external_write_performed=False, rollback_boot_verified=False)
            return
    first = journal.data['phase'] == 'new'
    journal.save(phase='maintenance_installing' if first else journal.data['phase'])
    maintenance = device.maintenance(first=first)
    try:
        known = journal.data.get('device')
        if known and known != maintenance.info:
            raise ValueError('Connected maintenance device differs from this run backup')
        journal.save(device=maintenance.info)
        if restore:
            load_backup(journal.path('backup_dir'))
            journal.save(phase='restore_started')
            report = journal.root/('restore-' + uuid.uuid4().hex + '.json')
            apply_image(maintenance, journal.path('backup_dir'), None, report, restore=True)
            journal.save(phase='original_layout_verified', restore_report=report.name)
        else:
            after_write = journal.data['phase'] in ('apply_started', 'migration_verified', 'target_installing')
            backup_dir = journal.path('backup_dir') if 'backup_dir' in journal.data else None
            if backup_dir:
                try:
                    load_backup(backup_dir)
                except (OSError, ValueError, KeyError):
                    if after_write:
                        raise ValueError('Verified original backup is missing; refuse to back up a partially migrated device')
                    backup_dir = None
            if backup_dir is None:
                name = 'backup-' + uuid.uuid4().hex
                journal.save(phase='backup_running', backup_dir=name)
                backup_dir = journal.path('backup_dir')
                say('双次读取并核对原外置 Flash 备份，备份只保存在本机。')
                backup(maintenance, backup_dir)
            manifest, original = load_backup(backup_dir)
            if manifest['device'] != maintenance.info:
                raise ValueError('Backup identity does not match the connected device')
            if 'migration_dir' not in journal.data:
                name = 'migration-' + uuid.uuid4().hex
                journal.save(phase='backup_verified', migration_dir=name)
            migration_dir = journal.path('migration_dir')
            if not (migration_dir/'migration.json').exists():
                if after_write:
                    raise ValueError('Migration plan missing after write; restore original backup')
                # A partial offline plan is abandoned, never reused or overwritten.
                if migration_dir.exists():
                    journal.save(migration_dir='migration-' + uuid.uuid4().hex)
                    migration_dir = journal.path('migration_dir')
                say('离线重建缩小的 LittleFS，保留文件、目录和属性。')
                prepare(backup_dir, bundle.root/bundle.manifest['files']['patch']['file'], migration_dir)
            image, plan = migration_dir/'migrated.bin', migration_dir/'migration.json'
            target = image.read_bytes()
            meta = json.loads(plan.read_text())
            expected_tail = bundle.assets['patch'] + b'\xff'*(0x20000-len(bundle.assets['patch']))
            if (meta['device'] != maintenance.info or meta['before_sha256'] != sha(original)
                    or meta['after_sha256'] != sha(target) or meta.get('inventory_equal_after_remount') is not True
                    or len(target) != END-START or target[-0x20000:] != expected_tail
                    or meta.get('patch_sha256') != sha(bundle.assets['patch'])
                    or meta.get('old_blocks') != 109 or meta.get('new_blocks') != 107
                    or meta.get('patch_offset') != 0x7e0000):
                raise ValueError('Migration plan no longer matches the verified backup/image')
            current = maintenance.region()
            if current == target:
                say('完整回读确认迁移已完成，继续安装录音固件。')
            elif current == original:
                journal.save(phase='apply_started')
                say('写入迁移后的文件系统及 Wi-Fi 补丁，并完整回读校验。')
                report = journal.root/('apply-' + uuid.uuid4().hex + '.json')
                apply_image(maintenance, backup_dir, image, report, plan_path=plan)
                journal.save(apply_report=report.name)
            else:
                raise ValueError('Flash is partly changed; stop and run restore with this same backup, never create a new backup')
            journal.save(phase='migration_verified')
    finally:
        maintenance.close()
    role = 'rollback' if restore else 'firmware'
    journal.save(phase='rollback_installing' if restore else 'target_installing')
    say('安装原布局回退固件。' if restore else '安装最新录音固件。')
    device.install(role)
    if restore:
        # Baseline USB is BLE-gated; a missing CDC port is not a boot failure.
        journal.save(phase='restored', rollback_boot_verified=False)
        say('原布局已回读校验，回退镜像已核对并发送重启；请检查屏幕/蓝牙。')
    else:
        result = device.verify_boot()
        journal.save(phase='complete', boot_check=result, migration_readback_verified=True)
        say('升级完成：镜像、外置 Flash 回读及启动通信检查通过；录音、Wi-Fi 和 BLE OTA 仍需功能验收。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('menu', 'inspect', 'run', 'resume', 'restore'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--usb-serial')
    parser.add_argument('--yes', action='store_true', help='skip the one pre-write confirmation')
    args = parser.parse_args(argv)
    journal = None
    try:
        bundle = Bundle(args.bundle)  # Validate every image/signature before USB access.
        if args.action == 'menu':
            say('1. 首次迁移及升级\n2. 继续上次升级\n3. 从原备份恢复\n4. 仅检查安装包')
            actions = {'1': 'run', '2': 'resume', '3': 'restore', '4': 'inspect'}
            args.action = actions.get(input('请选择：').strip())
            if args.action is None:
                raise ValueError('Invalid menu selection')
            if args.action in ('resume', 'restore'):
                args.state_dir = Path(input('请输入上次显示的备份与恢复目录：').strip().strip('"'))
        if args.action == 'inspect':
            say(json.dumps({'bundle_verified': True, 'layout': bundle.manifest['layout'], 'images': bundle.images}))
            return 0
        if sys.platform != 'darwin':
            raise RuntimeError('This delivery tool supports macOS only')
        if args.action != 'run' and args.state_dir is None:
            raise ValueError('resume/restore requires the original --state-dir')
        root = args.state_dir or Path.home()/'Library/Application Support/reSpeaker Clip Upgrade/Runs'/(
            time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        journal = Journal(root, bundle.fingerprint)
        if args.action == 'run' and journal.data['phase'] != 'new':
            raise ValueError('Existing run found; use resume or restore, not run')
        if args.action == 'resume' and journal.data['phase'] in ('restore_started', 'original_layout_verified', 'rollback_installing', 'restored'):
            raise ValueError('This is a restore run; continue with restore')
        say(f'本机备份与恢复记录：{journal.root}')
        say('请停止录音，使用可靠数据线直连 Mac，并保持供电。首次请进入 Recovery Mode。')
        if not args.yes and input('确认执行迁移/升级（恢复操作会还原原配置），输入 YES 继续：').strip() != 'YES':
            say('已取消，未连接或写入设备。')
            return 2
        with journal.lock(), prevent_sleep():
            backend = MacUSB(bundle, journal, args.usb_serial)
            execute(bundle, journal, backend, restore=args.action == 'restore')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Keep the write-ahead journal unchanged, especially if another process
        # owns its lock. It is the authority for partial-write recovery.
        if journal:
            try:
                private_write(journal.root/('error-'+uuid.uuid4().hex+'.json'), json.dumps({
                    'time': time.time(), 'phase': journal.data['phase'], 'error': type(error).__name__}).encode())
            except OSError:
                pass
        say(f'已停止：{error if isinstance(error, Exception) else "用户中断"}')
        if journal:
            say(f'保留 USB 连接及原备份。用相同安装包和 --state-dir "{journal.root}" 执行 resume；部分写入须执行 restore。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
