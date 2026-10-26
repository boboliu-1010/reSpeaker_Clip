#!/usr/bin/env bash
# Build the desktop entry point and package a drag-to-Applications disk image.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
if [[ "${1:-}" != "--skip-build" ]]; then
  cd "$ROOT/mobile/app"
  flutter pub get
  flutter build macos --release -t lib/desktop_main.dart
fi
APP="$ROOT/mobile/app/build/macos/Build/Products/Release/Boa Voice.app"
[[ -d "$APP" ]] || { echo "Release app missing: $APP" >&2; exit 1; }
python3 "$ROOT/scripts/verify-macos-bundle.py" "$APP"
# Flutter incremental builds can refresh App.framework after Xcode sealed the
# outer bundle. Seal generated Dart assets first, then the app, before copying.
SIGN_IDENTITY="${MACOS_CODESIGN_IDENTITY:--}"
codesign --force --sign "$SIGN_IDENTITY" "$APP/Contents/Frameworks/App.framework"
codesign --force --sign "$SIGN_IDENTITY" --entitlements "$ROOT/mobile/app/macos/Runner/Release.entitlements" "$APP"
codesign --verify --deep --strict "$APP"
# Keep the prerelease suffix; Apple's native bundle version may strip it.
PACKAGE_VERSION=$(sed -n 's/^version: *//p' "$ROOT/mobile/app/pubspec.yaml")
VERSION="${PACKAGE_VERSION%%+*}"
BUILD_NUMBER="${PACKAGE_VERSION##*+}"
APP_BUILD_NUMBER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")
[[ "$APP_BUILD_NUMBER" == "$BUILD_NUMBER" ]] || { echo 'App build number differs from pubspec.yaml; rebuild first' >&2; exit 1; }
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] || { echo 'Invalid version' >&2; exit 1; }
ARCHS=$(lipo -archs "$APP/Contents/MacOS/Boa Voice")
if [[ "$ARCHS" == *arm64* && "$ARCHS" == *x86_64* ]]; then
  FLAVOR=universal
elif [[ "$ARCHS" == *arm64* ]]; then
  FLAVOR=arm64
else
  FLAVOR=x86_64
fi
OUT="$ROOT/dist"
mkdir -p "$OUT"
IMAGE="$OUT/Boa-Voice-$VERSION-macos-$FLAVOR.dmg"
[[ ! -e "$IMAGE" ]] || { echo "Already exists; move the previous image before packaging: $IMAGE" >&2; exit 1; }
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/boa-dmg.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/Boa Voice.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/安装说明.txt" <<TXT
Boa Voice macOS $VERSION

安装：将 Boa Voice.app 拖到 Applications，等待复制完成，再推出此磁盘映像。
首次使用麦克风与 Clip 蓝牙时，需要允许对应系统权限。
若提示“Apple 无法验证”，先点完成，再到系统设置 → 隐私与安全性，
在 Boa Voice 被阻止提示旁点击“仍要打开”，由本人完成系统确认。

服务设置：填 Boa Server 的 HTTPS 地址和用户令牌。开发证书可在 App 中导入。
Clip 设备：连接蓝牙后配置 Wi-Fi、Server 与设备令牌，再开启自动上传。
音频存储 Server 独立运行，安装 App 不会启动 Server。
安装及配置说明：
https://github.com/boboliu-1010/reSpeaker_Clip/blob/boa/dtls-desktop-beta4/README-desktop.md

此 Beta 版本用于本机开发与自用，采用本机临时签名，未经过 Apple 公证。
TXT
hdiutil create -volname 'Boa Voice' -srcfolder "$STAGE" -fs HFS+ -format UDZO "$IMAGE"
hdiutil verify "$IMAGE"
(cd "$OUT" && shasum -a 256 "$(basename "$IMAGE")" > "$(basename "$IMAGE").sha256")
printf 'Created: %s\n' "$IMAGE"
