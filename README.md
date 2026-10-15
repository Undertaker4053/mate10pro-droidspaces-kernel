# Mate 10 Pro BLA / EMUI 9.1 KernelSU + DroidSpaces

The first full DroidSpaces build was reported to bootloop. Recovered kernel
logs confirm panics during UNIX datagram / SLUB allocation. The exact cause
is not yet established. Do not treat that image as a working release.

The manual workflow now builds two diagnostic variants: `baseline` reproduces
the original config without DroidSpaces patches, and `no-memcg` retains the
DroidSpaces changes except MEMCG and restores its dependent TASK_PROTECT_LRU
setting. The latter is a hypothesis test, not a verified fix. Both variants
include System.map and compressed vmlinux with debug information. SCM suffixes
are suppressed so the baseline release matches the original. Neither image
is automatically flashed. Recovered device logs remain local.

Rebuild the Huawei Linux 4.9.148 BLA kernel with the kernel features needed by
[DroidSpaces](https://github.com/ravindu644/Droidspaces-OSS).
This repository builds the kernel. Install the DroidSpaces app separately.

The source image matches the upstream v21.0 `BLA_EMUI9.1_KernelSU.img` SHA-256.
The build starts from its embedded configuration and preserves its Android boot
header fields, including its original command line. Only the kernel size, boot
payload hash and kernel payload change. The release string identifies DroidSpaces.
KernelSU remains at upstream v0.9.2, with the existing manual hooks.

## Build

Open Actions, select **Build BLA KernelSU diagnostic kernels**, then **Run workflow**.
The artifact contains the image, SHA-256, complete configuration, configuration
diff, source patch, rebuilt modules, Module.symvers and build log.
Source and toolchain commits are pinned in `sources.json` and `build.sh`.

## Huawei 4.9 adaptations

- Enable IPC, PID, UTS, user and network namespaces, SysV IPC, POSIX queues,
  cgroup devices/memory/CPU bandwidth, veth, bridge, macvlan and NAT support.
- Keep Huawei's existing PIDs cgroup controller, which already provides
  `pids.max` and `pids.current`. Enabling the standard controller alongside it
  duplicates `SUBSYS(pids)` and does not compile.
- Apply the two upstream non-GKI compatibility fixes. The cgroup fix is adapted
  to this tree's `kernel/cgroup.c` rather than `kernel/cgroup/cgroup.c`.
- The qtaguid fix disables live `dev_get_stats` reads in `iface_stat_fmt`; its
  live interface counters can therefore differ from the original kernel.
- Do not add `FW_LOADER_COMPRESS` or the generic
  `NETFILTER_XT_TARGET_MASQUERADE`: these symbols are absent in this kernel.
  The IPv4/IPv6 MASQUERADE targets are enabled instead.
- Use the 4.9 conntrack netlink symbol `NF_CT_NETLINK` in place of the guide's
  `NF_CONNTRACK_NETLINK` spelling.
- Preserve SELinux and the original KernelSU configuration. No permissive
  kernel variant is generated.

This is a new experimental build, not a verified replacement for every BLA
firmware. Kernel module CRCs may change when enabling namespaces and memory
cgroups; the artifact includes modules rebuilt from the new configuration.
Building successfully does not verify phone boot, vendor module compatibility
or container operation. No automatic flashing is performed.

After device validation, use the DroidSpaces app's Requirements check or
`droidspaces check`. A kernel 4.9 build should be paired with a distribution
supported by DroidSpaces on that kernel; its guide documents systemd limits.

The kernel retains its upstream GPL-2.0 licensing. The two compatibility patches
derive from DroidSpaces' documented kernel patches; see their original headers
and the pinned upstream repository in `sources.json` for provenance.
