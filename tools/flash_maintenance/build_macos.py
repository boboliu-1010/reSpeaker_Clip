"""Developer-only builder: freeze Python/dependencies into an offline Mac delivery.

Users run the delivered .command launcher; they do not install Python or nrfutil.
Build separately on Apple Silicon and Intel. Device qualification, Developer ID
signing and notarization remain release steps, not inferred from packaging.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

from firmware_package import Bundle, LAYOUT, ROLES


def assemble(root, files, config):
    values = set(config.read_text().splitlines())
    required = {'CONFIG_CLIP_UPLOAD=y', 'CONFIG_NRF_WIFI_PATCHES_EXT_FLASH_STORE=y'}
    if not required <= values:
        raise ValueError('Target build config is not the external-patch upload preset')
    root.mkdir(parents=True, exist_ok=False)
    names = {'maintenance': 'maintenance.signed.bin', 'firmware': 'firmware.signed.bin',
             'rollback': 'rollback.signed.bin', 'patch': 'nrf70.bin', 'public_key': 'signing-public.pem'}
    manifest = {'schema': 1, 'layout': LAYOUT, 'files': {},
                'target_config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                'qualification': 'development; end-to-end device migration must be validated before distribution'}
    for role in ROLES:
        data = files[role].read_bytes()
        (root/names[role]).write_bytes(data)
        manifest['files'][role] = {'file': names[role], 'sha256': hashlib.sha256(data).hexdigest()}
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    Bundle(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ROLES:
        parser.add_argument('--'+role.replace('_', '-'), type=Path, required=True)
    parser.add_argument('--firmware-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Build this delivery on macOS for its native architecture')
    output = args.output.resolve()
    archive_path = output.with_suffix('.zip')
    if output.exists() or archive_path.exists():
        parser.error('Output directory and ZIP must not already exist')
    source = Path(__file__).resolve().parent
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='clip-upgrade-build-') as directory:
        stage = Path(directory)
        delivery = stage/output.name
        assemble(delivery/'bundle', {k: getattr(args, k).resolve() for k in ROLES}, args.firmware_config)
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--onedir', '--name', 'clip-upgrade', '--console',
                        '--collect-submodules', 'littlefs',
                        '--distpath', str(stage/'dist'), '--workpath', str(stage/'work'),
                        '--specpath', str(stage/'spec'), str(source/'upgrade.py')], check=True)
        shutil.copytree(stage/'dist/clip-upgrade', delivery/'bin')
        launcher = delivery/'开始升级.command'
        launcher.write_text('''#!/bin/zsh
clip_upgrade_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
"$clip_upgrade_dir/bin/clip-upgrade" menu --bundle "$clip_upgrade_dir/bundle"
clip_upgrade_status=$?
echo "按回车关闭此窗口。"
read -r clip_upgrade_close
exit "$clip_upgrade_status"
''')
        launcher.chmod(0o755)
        (delivery/'使用说明.txt').write_text('''Clip USB 迁移升级程序（开发验证包）

无需安装 Python、SDK 或 nrfutil；本包仅适用于构建时对应的 Mac 架构。
解压后保留全部目录，连接 USB 数据线，双击“开始升级.command”。
首次先停止录音，再让设备进入 Recovery Mode，按提示确认后开始。
第一次运行可选择“仅检查安装包”，不访问设备。
如果 macOS 因来源限制阻止运行，请先联系分发者；此开发包未完成 Developer ID 签名和公证，不要关闭系统安全机制。

请保持 Mac 和设备供电，不要拔线或让电脑休眠。退出其他使用串口的软件。
程序会显示备份与恢复目录。保留该目录：它包含设备配置和蓝牙密钥，不要上传或分享。
失败后重新运行本程序，选择“继续上次升级”并输入原目录。
若提示部分写入，选择“从原备份恢复”。不要重新创建备份覆盖原始状态。
恢复会还原原外置布局及配置，再安装本包的原布局回退镜像；旧版 USB 可能默认关闭，请观察屏幕和蓝牙确认启动。

兼容性由本包的已知原厂应用镜像和分区决定；未知出厂版本会拒绝。
仅更新应用核，保留原 Bootloader、网络核及 SD 录音；仍需验证目标设备的签名密钥兼容性。
完成提示只代表镜像、外置 Flash 回读和启动通信检查，不代替录音、Wi-Fi、上传及 BLE OTA 功能验收。
本包尚未通过完整实机迁移验收，正式分发前需完成验证、签名和公证。
''')
        (delivery/'build.json').write_text(json.dumps({'architecture': platform.machine(),
            'macos': platform.mac_ver()[0], 'runtime': sys.version, 'device_tested': False,
            'developer_id_signed': False, 'notarized': False}, indent=2)+'\n')
        notices = delivery/'licenses'
        notices.mkdir()
        inventory = []
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata['Name']
            inventory.append({'name': name, 'version': distribution.version})
            for item in distribution.files or ():
                if item.name.lower().startswith(('license', 'copying', 'notice', 'authors')):
                    path = distribution.locate_file(item)
                    if path.is_file():
                        folder = notices/name
                        folder.mkdir(exist_ok=True)
                        shutil.copy2(path, folder/item.name)
        (notices/'packages.json').write_text(json.dumps(inventory, indent=2)+'\n')
        # Exercise the frozen executable before delivering it. This is read-only.
        subprocess.run([str(delivery/'bin/clip-upgrade'), 'inspect', '--bundle', str(delivery/'bundle')], check=True)
        shutil.copytree(delivery, output)
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                archive.write(path, arcname=str(Path(output.name)/path.relative_to(output)))
    print(json.dumps({'directory': str(output), 'zip': str(archive_path), 'architecture': platform.machine()}))


if __name__ == '__main__':
    main()
