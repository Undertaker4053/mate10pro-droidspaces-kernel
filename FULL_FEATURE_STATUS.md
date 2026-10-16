# Full-feature DroidSpaces / Docker investigation — 2026-10-16

No full-feature image is ready to flash. The phone is running the booted
baseline; no phone partition writes or reboots were performed in this phase.

| Variant | Evidence | Use |
| --- | --- | --- |
| baseline | Manually booted on the phone | Known bootable recovery/reference image |
| original full / no-MEMCG | Manual boot failures; kernel panics | Do not flash again as a fix |
| compat | CI succeeded; selected shared layouts checked | Offline control, untested on hardware; lacks requested features |
| full-C | Configuration checks passed; C backport compiled and passed semantic/ELF/assembly checks | Default diagnostic mode; explicit experimental candidate option |

## Confirmed source defect

Seventeen Huawei files are C code pre-generated as `.S`, including block,
page-cache and network components. Their embedded debug layouts remain stock
when the kernel C structures change. In the failed no-MEMCG kernel, for example,
`sock` is 944 bytes instead of 936, and `sk_buff` 264 instead of 256. Assembly
still addresses the old layouts. The recovered panic is a corrupt UNIX socket
queue unlink. This establishes an unsafe ABI mismatch; it does not establish
the full causal sequence of each panic.

## Why switching off the vendor block layer is incomplete

Pinned source: [Huawei 4.9 tree](https://github.com/xixiaobei-bei/KernelSU_on_Huawei/tree/3c2994fdea8ccd1bda22bcaa6a3a04ddc89764aa).

* `include/linux/blk_types.h`: `hisi_bio` and its key, key length/index and DUN
  metadata are gated by `CONFIG_HISI_BLK`.
* `include/linux/blkdev.h`: request-side `hisi_req` metadata and vendor helpers
  are also tied to that option.
* `fs/f2fs/data.c` and `fs/direct-io.c` produce encrypted BIO metadata.
* `drivers/scsi/ufs/ufs-kirin.c`, `ufs_kirin_uie_utrd_prepare`, consumes the
  request key and BIO index to prepare UFS crypto descriptors.
* `block/hisi-blk-core.S` contains request initialization, BIO splitting and
  merging crypto logic. Generic paths do not simply replace those operations.
* `block/partition-generic.c` also calls `hisi_blk_check_partition_done`
  unconditionally, exposing another incomplete fallback.

Adding missing fields alone does not preserve initialization, key propagation,
split DUN adjustment or encrypted merge constraints. Deleting encryption code,
turning off encryption, or making the missing helpers unconditional no-ops
would conceal the defect rather than resolve it.

## Available references and limits

An older [OpenKirin Linux 4.1 implementation](https://github.com/OpenKirin/android_kernel_huawei_hi6250/tree/a5c1fdbf21d0750a69166acf65b21d324b882d60)
does not cover the current block implementation.

A newer [Huawei Linux 4.14 MAS core implementation](https://github.com/R0rt1z2/android_kernel_huawei_franklin/blob/73523667a5c7634b870341cdfc6f4ca22b9706b7/_mas_block/mas-blk-core.c)
contains readable inline-crypto helpers for initialization, key-aware merging,
and split metadata propagation. It is a porting reference, not a drop-in
replacement for this 4.9 tree. No complete matching 4.9 C replacement for all
seventeen generated components has been located in the repositories reviewed.

## Requirements before a full-feature image can be offered

1. Supply matching recompilable vendor C, or implement and audit the 4.9 C
   replacement for the complete encrypted I/O path, including allocation/reset,
   cloning, splitting, request initialization and merge constraints.
2. Validate encrypted and unencrypted I/O cases, including front/back merges,
   partial BIOs, direct I/O and device-mapper paths. Inspect the final linked
   kernel to ensure fixed-layout vendor code has not re-entered the build.
3. Pass configuration and image checks, then test boot/storage and actual
   namespace/cgroup/network/Docker behavior. These runtime results do not yet
   exist; a successful Actions badge would not establish them.

The intended scope includes SysV/POSIX IPC, PID/UTS/network namespaces,
memory/swap and CPU controls, cgroup devices, bridge/NAT/veth/macvlan,
overlay filesystem and normal Docker container support. An isolated Linux
container still shares the Android kernel; it is not a virtual machine with
its own kernel. Compatibility with every modern rootfs or Docker version on
Linux 4.9 cannot be claimed from configuration checks alone.

The C implementation and its current evidence are documented in
[C_PORT_STATUS.md](C_PORT_STATUS.md). Default full-C builds remain diagnostic;
explicit candidate mode packages a manual-test image only after all offline
checks pass. This does not meet the boot/storage/runtime requirements for a
validated release. Raw phone logs remain local.
