#!/bin/bash
set -euo pipefail
plugin_dir="$(cd "$(dirname "$0")" && pwd)"
app_dir="$(cd "$plugin_dir/../.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
cmake -S "$app_dir/../../lib/opus/opus" -B "$app_dir/build/opus-simulator" -G Xcode \
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT=iphonesimulator \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=15.0 \
  -DOPUS_BUILD_FRAMEWORK=ON -DOPUS_BUILD_TESTING=OFF -DOPUS_BUILD_PROGRAMS=OFF \
  -DOPUS_INSTALL_PKG_CONFIG_MODULE=OFF -DOPUS_INSTALL_CMAKE_CONFIG_MODULE=OFF
cmake --build "$app_dir/build/opus-simulator" --config Release --parallel 4
if [ ! -d "$plugin_dir/ios/original-opus.xcframework" ]; then
  dart pub cache add opus_flutter_ios --version 3.0.1
  cp -R "${PUB_CACHE:-$HOME/.pub-cache}/hosted/pub.dev/opus_flutter_ios-3.0.1/ios/opus.xcframework" \
    "$plugin_dir/ios/original-opus.xcframework"
fi
# Create into a temporary path; only replace our generated output after success.
output_dir="$(mktemp -d "$app_dir/build/opus-xcframework.XXXXXX")"
cp -R "$app_dir/build/opus-simulator/Release-iphonesimulator/Opus.framework" "$output_dir/opus.framework"
# CMake names the binary Opus; the plugin's device framework uses lowercase.
# Normalize both the executable and dylib ID for the simulator's filesystem.
mv "$output_dir/opus.framework/Opus" "$output_dir/opus.framework/opus-renaming"
mv "$output_dir/opus.framework/opus-renaming" "$output_dir/opus.framework/opus"
plutil -replace CFBundleExecutable -string opus "$output_dir/opus.framework/Info.plist"
xcrun install_name_tool -id '@rpath/opus.framework/opus' "$output_dir/opus.framework/opus"
codesign --force --sign - "$output_dir/opus.framework"
xcodebuild -create-xcframework \
  -framework "$plugin_dir/ios/original-opus.xcframework/ios-arm64/opus.framework" \
  -framework "$output_dir/opus.framework" \
  -output "$output_dir/opus.xcframework"
if [ -d "$plugin_dir/ios/opus.xcframework" ]; then
  mv "$plugin_dir/ios/opus.xcframework" "$output_dir/previous-opus.xcframework"
fi
mv "$output_dir/opus.xcframework" "$plugin_dir/ios/opus.xcframework"
