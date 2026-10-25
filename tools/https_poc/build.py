"""Reproducible app-only HTTPS/DTLS builds in isolated NCS build directories."""
import argparse
import os
from pathlib import Path
import subprocess

PRESETS = {
    "dtls-optimized": (
        "runtime.conf", "dtls-netdiag.conf",
        "https-wifi-no-stbc.conf", "https-arp-backport.conf", "dtls-upload.conf",
        "wifi-auth-log.conf", "dtls-aead-hardware.conf",
        "dtls-upload-optimized.conf", "dtls-profile.conf",
    ),
}
PRESETS["dtls-single"] = (*PRESETS["dtls-optimized"], "dtls-single.conf")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ncs", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--preset", choices=PRESETS,
                        help="named full-application candidate configuration")
    parser.add_argument("--extra-conf", type=Path, action="append", default=[],
                        help="additional app-only config, appended after the transport base")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    ca = args.ca.resolve()
    content = ca.read_text()
    if "BEGIN CERTIFICATE" not in content or "PRIVATE KEY" in content:
        parser.error("--ca must contain only public CA certificate(s)")
    build = args.build.resolve()
    if build.name in ("build-clip-prod", "build-clip-ext-patch"):
        parser.error("refusing to overwrite the baseline build")
    env = dict(os.environ, ZEPHYR_EXTRA_MODULES=str(repo),
               ZEPHYR_SDK_INSTALL_DIR=str(args.sdk.resolve()), CLIP_HTTPS_CA_FILE=str(ca))
    overlays = [*[repo / "applications/clip" / name for name in PRESETS.get(args.preset, ())],
                *[p.resolve() for p in args.extra_conf]]
    if any(not p.is_file() for p in overlays):
        parser.error("each --extra-conf must be an existing file")
    # Decide from the effective ordered transport selection, including manual
    # --extra-conf DTLS builds, rather than inheriting the old HTTPS sockets.
    dtls = False
    for overlay in overlays:
        for line in overlay.read_text().splitlines():
            if line.strip() in ("CONFIG_CLIP_DTLS_UPLOAD=y", "CONFIG_CLIP_DTLS_UPLOAD=n"):
                dtls = line.strip().endswith("=y")
    configs = [repo / "applications/clip" / ("dtls.conf" if dtls else "https.conf"), *overlays]
    command = ["west", "build", "--cmake", "--sysbuild", "-b", "clip/nrf5340/cpuapp",
               str(repo / "applications/clip"), "-d", str(build), "--",
               "-DSNIPPET=production", "-DSNIPPET_ROOT=" + str(repo / "applications/clip"),
               "-Dclip_EXTRA_CONF_FILE=" + ";".join(map(str, configs))]
    build.parent.mkdir(parents=True, exist_ok=True)
    log = build.parent / (build.name + ".log")
    with log.open("w") as output:
        result = subprocess.run(command, cwd=args.ncs, env=env, stdout=output, stderr=subprocess.STDOUT)
    print("\n".join(log.read_text().splitlines()[-70:]))
    print(f"Full build log: {log}")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
