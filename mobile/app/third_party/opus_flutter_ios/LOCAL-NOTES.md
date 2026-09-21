# Local Apple Silicon simulator support

Based on the published `opus_flutter_ios` 3.0.1 package. Original LICENSE,
README, Dart registration, and native plugin sources are retained. The local
pubspec permits Dart 3, as used by this project.

The published XCFramework contains an iOS arm64 device slice and an x86_64
simulator slice, but no arm64 simulator slice. Our `build-simulator.sh`
builds the repository's libopus source for the actual iOS simulator SDK,
then combines it with the original device framework. It does not retag a
device binary as a simulator binary. This output supports Apple Silicon
simulators and arm64 devices; Intel simulator support is not included.

Requirements: Xcode, CMake, Dart/Flutter. From `mobile/app`:

```sh
bash third_party/opus_flutter_ios/build-simulator.sh
flutter pub get
cd ios
pod install
```

Generated XCFrameworks are ignored by Git. The script fetches the original
3.0.1 package into the standard pub cache if necessary, without editing the
cached package. Rebuild after changes to the vendored libopus source.
The libopus license is at `../../../../lib/opus/opus/COPYING` relative
to this package directory. Also retain the repository's
`lib/opus/opus/LICENSE_PLEASE_READ.txt` and source notices.

This is a local build compatibility patch. Real audio decoding, physical
device playback, release signing, and distribution licensing need their
own validation; a successful simulator launch is not that validation.
