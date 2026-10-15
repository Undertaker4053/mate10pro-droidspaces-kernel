#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
mkdir -p artifacts
exec > >(tee -a "$ROOT/artifacts/build.log") 2>&1

fetch_repo() {
    local directory=$1 url=$2 revision=$3
    git init "$directory"
    git -C "$directory" remote add origin "$url"
    git -C "$directory" fetch --depth=1 origin "$revision"
    git -C "$directory" checkout --detach FETCH_HEAD
}

fetch_repo kernel https://github.com/xixiaobei-bei/KernelSU_on_Huawei.git 3c2994fdea8ccd1bda22bcaa6a3a04ddc89764aa
fetch_repo kernel/KernelSU https://github.com/tiann/KernelSU.git 3291538446b7fccec46fa52775e6bf594c77b9f4
fetch_repo toolchain https://github.com/LineageOS/android_prebuilts_gcc_linux-x86_aarch64_aarch64-linux-android-4.9.git 5e030eafe024784a73cdf47e6936ac0dbfc763dc

export ARCH=arm64
export CROSS_COMPILE="$ROOT/toolchain/bin/aarch64-linux-android-"
export CROSS_COMPILE_ARM32=arm-linux-gnueabi-
export KBUILD_BUILD_USER=builder
export KBUILD_BUILD_HOST=github-actions
"${CROSS_COMPILE}gcc" --version

cd kernel
git apply --check "$ROOT/01-qtaguid.patch" "$ROOT/02-cgroup-prefix.patch"
git apply "$ROOT/01-qtaguid.patch" "$ROOT/02-cgroup-prefix.patch"
git diff --check
git diff --binary > "$ROOT/artifacts/applied-source.patch"
mkdir -p out
gzip -dc "$ROOT/original.config.gz" > out/original.config
scripts/kconfig/merge_config.sh -m -O out out/original.config "$ROOT/droidspaces.config"
make O=out PYTHON=python2 olddefconfig
python3 "$ROOT/verify_config.py" out/.config "$ROOT/droidspaces.config"
cp out/.config "$ROOT/artifacts/kernel.config"
python2 scripts/diffconfig out/original.config out/.config > "$ROOT/artifacts/config-changes.txt"
make O=out PYTHON=python2 -j"$(nproc)" Image.gz modules
python3 "$ROOT/repack.py" "$ROOT/boot-header.bin" out/arch/arm64/boot/Image.gz "$ROOT/artifacts/BLA_EMUI9.1_KernelSU_DroidSpaces.img"
cp out/Module.symvers "$ROOT/artifacts/Module.symvers"
find out -name '*.ko' -print0 | tar --null -T - -czf "$ROOT/artifacts/rebuilt-modules.tar.gz"
cp "$ROOT/sources.json" "$ROOT/artifacts/sources.json"
printf '%s\n' 'Build completed. Flashing and runtime container checks have not been performed.'
