#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
BUILD_VARIANT=${BUILD_VARIANT:-droidspaces}
case "$BUILD_VARIANT" in
    baseline|no-memcg|droidspaces|compat|full-c) ;;
    *) printf 'Unknown build variant: %s\n' "$BUILD_VARIANT" >&2; exit 1 ;;
esac
mkdir -p artifacts
exec > >(tee -a "$ROOT/artifacts/build.log") 2>&1
if [[ "$BUILD_VARIANT" == full-c ]]; then
    printf '%s\n' 'BLOCKED: Huawei inline-encryption C migration is incomplete; no flash image is produced.' > "$ROOT/artifacts/DO-NOT-FLASH.txt"
fi

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
export PATH="$ROOT/toolchain/bin:$PATH"
export CROSS_COMPILE="$ROOT/toolchain/bin/aarch64-linux-android-"
export CROSS_COMPILE_ARM32=arm-linux-gnueabi-
export KBUILD_BUILD_USER=builder
export KBUILD_BUILD_HOST=github-actions
"${CROSS_COMPILE}gcc" --version
aarch64-linux-android-cpp --version

cd kernel
if [[ "$BUILD_VARIANT" == droidspaces || "$BUILD_VARIANT" == no-memcg || "$BUILD_VARIANT" == full-c ]]; then
    git apply --check "$ROOT/01-qtaguid.patch" "$ROOT/02-cgroup-prefix.patch"
    git apply "$ROOT/01-qtaguid.patch" "$ROOT/02-cgroup-prefix.patch"
fi
if [[ "$BUILD_VARIANT" == compat ]]; then
    git apply --check "$ROOT/03-posix-mqueue-abi.patch"
    git apply "$ROOT/03-posix-mqueue-abi.patch"
fi
if [[ "$BUILD_VARIANT" == full-c ]]; then
    git apply --check "$ROOT/04-hisi-block-fallback.patch"
    git apply "$ROOT/04-hisi-block-fallback.patch"
fi
git diff --check
git diff --binary > "$ROOT/artifacts/applied-source.patch"
# Match the original release for the baseline; do not add SCM hash/dirty suffixes.
: > .scmversion
mkdir -p out
gzip -dc "$ROOT/original.config.gz" > out/original.config
if [[ "$BUILD_VARIANT" == baseline ]]; then
    cp out/original.config out/.config
    expected_config=out/original.config
    image_name=BLA_EMUI9.1_KernelSU_baseline.img
else
    if [[ "$BUILD_VARIANT" == compat ]]; then
        cp "$ROOT/compat.config" out/variant.config
    elif [[ "$BUILD_VARIANT" == full-c ]]; then
        cp "$ROOT/full-c.config" out/variant.config
    else
        cp "$ROOT/droidspaces.config" out/variant.config
    fi
    image_name=BLA_EMUI9.1_KernelSU_DroidSpaces.img
    if [[ "$BUILD_VARIANT" == compat ]]; then
        image_name=BLA_EMUI9.1_KernelSU_DroidSpaces_compat.img
    fi
    if [[ "$BUILD_VARIANT" == full-c ]]; then
        image_name=BLA_EMUI9.1_KernelSU_DroidSpaces_Docker_fullC.img
    fi
    if [[ "$BUILD_VARIANT" == no-memcg ]]; then
        sed -i 's/^CONFIG_MEMCG=y$/# CONFIG_MEMCG is not set/' out/variant.config
        sed -i 's/KernelSU_DroidSpaces_xixiaobei@Github/KernelSU_DroidSpaces_noMEMCG/' out/variant.config
        printf '%s\n' 'CONFIG_TASK_PROTECT_LRU=y' >> out/variant.config
        image_name=BLA_EMUI9.1_KernelSU_DroidSpaces_noMEMCG.img
    fi
    scripts/kconfig/merge_config.sh -m -O out out/original.config out/variant.config
    expected_config=out/variant.config
fi
make O=out PYTHON=python2 olddefconfig
python3 "$ROOT/verify_config.py" out/.config "$expected_config"
cp "$expected_config" "$ROOT/artifacts/expected.config"
cp out/.config "$ROOT/artifacts/kernel.config"
python2 scripts/diffconfig out/original.config out/.config > "$ROOT/artifacts/config-changes.txt"
if [[ "$BUILD_VARIANT" == full-c ]]; then
    # Collect independent fallback compile errors in one CI run; any error still fails the build.
    make O=out PYTHON=python2 -k -j"$(nproc)" Image.gz modules
else
    make O=out PYTHON=python2 -j"$(nproc)" Image.gz modules
fi
if [[ "$BUILD_VARIANT" == compat ]]; then
    python3 "$ROOT/verify_vendor_layouts.py" out/vmlinux . "$ROOT/artifacts/vendor-layout-check.json"
fi
if [[ "$BUILD_VARIANT" == full-c ]]; then
    python3 "$ROOT/verify_no_vendor_asm.py" out/vmlinux . out "$ROOT/artifacts/vendor-assembly-check.json"
fi
cp out/System.map "$ROOT/artifacts/System.map"
gzip -1 -c out/vmlinux > "$ROOT/artifacts/vmlinux.gz"
if [[ "$BUILD_VARIANT" == full-c ]]; then
    # Deliberate release gate: removing HISI_BLK also removes inline-encryption
    # metadata and propagation hooks. A successful compile/ASM scan alone does
    # not validate encrypted I/O. Keep this variant diagnostic-only until a
    # reviewed C implementation and its regression evidence replace this gate.
    printf '%s\n' 'BLOCKED: Huawei inline-encryption C migration is incomplete; no flash image is produced.' | tee "$ROOT/artifacts/DO-NOT-FLASH.txt"
    exit 2
fi
python3 "$ROOT/repack.py" "$ROOT/boot-header.bin" out/arch/arm64/boot/Image.gz "$ROOT/artifacts/$image_name"
printf '%s\n' "$BUILD_VARIANT" > "$ROOT/artifacts/build-variant.txt"
cp out/Module.symvers "$ROOT/artifacts/Module.symvers"
find out -name '*.ko' -print0 | tar --null -T - -czf "$ROOT/artifacts/rebuilt-modules.tar.gz"
cp "$ROOT/sources.json" "$ROOT/artifacts/sources.json"
printf '%s\n' 'Build completed. Flashing and runtime container checks have not been performed.'
