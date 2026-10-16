# First C-port implementation — 2026-10-16

This is diagnostic source work. There is no new image to flash and no claim of
successful boot or encrypted disk I/O. Full-C image packaging stays blocked.

## Implemented

`05-inline-crypto-c-port.patch`, applied after patch 04 to the pinned 4.9 tree:

* Introduces compact BIO/request crypto metadata only when UFS inline crypto is
  enabled and HISI_BLK is disabled. Existing filesystem and UFS field accessors
  remain intact; the stock HISI_BLK structure layouts are unchanged.
* Resets request key state on legacy allocation and blk-mq reuse, initializes
  it from the BIO, and carries it across BIO/request clones and clone submission.
* Copies metadata in both BIO clone APIs. Tracks logical data-unit indexes in
  bio_advance, covering split, trim and partial completion through that API.
  This avoids deriving direct-I/O logical indexes from user pages' page->index.
* Checks key pointer, 64-byte length, keyslot and data-unit continuity before
  merges. Partial-unit encrypted BIOs conservatively do not merge. Uses current
  byte counts rather than a stale bi_vcnt after splitting.
* Checks crypto compatibility before request segment accounting is changed.
* Guards partition bookkeeping and UFS idle notifications that require HISI_BLK.
  It does not remove partition parsing or UFS interrupt handling.

Patch 06 places request-key initialization in `blk_rq_bio_prep`, the shared
entry point also used by SCSI passthrough's `blk_rq_append_bio`. The final-ELF
check requires this central caller rather than just the filesystem request path.

The build verifies no edits to the pinned `ufs-kirin.c` hardware crypto code,
F2FS/direct-I/O key producers or dm-row implementation. UFS inline crypto,
enhanced crypto, F2FS encryption and ext4 encryption remain enabled. The newer
48-byte/V3 crypto formats are not introduced.

## Source and provenance

The core reference is Huawei's GPLv2
[kirin970 mas_blk_inline_crypt.c](https://github.com/hisi-oss/android_kernel_huawei_kirin970/blob/f39fdf340fe2ee29db13cb8838653161d6ad7c57/block/mas_blk_inline_crypt.c),
Linux 4.14.116. The C-port header preserves Huawei's copyright and license.
The four relevant 4.9 generated assembly functions were also inspected for their
existing 64-byte key, split and merge behavior. This is a backport and additional
lifecycle work, not a drop-in copy of a different kernel.

The locally provided BLA_PIE_EMUI9.1.0 source archive is 4.9.148, dated
2019-11-29. Its seventeen relevant generated files are byte-identical to the
current pinned source; no matching C replacements were found in that archive.

## Validation and remaining limits

* Both patches apply cleanly to pinned source files.
* Actual helper C compiles and runs in native Windows host tests using an
  isolated Zig 0.13 compiler: 33 crypto semantic assertions, 4 stock-path stub
  assertions, 4 crypto-off stub assertions, plus two rejection cases for invalid
  key length and index overflow. The kernel types for the crypto contexts are
  extracted from the patched header. The host block-I/O model is not hardware.
* Actions repeats these tests with the Ubuntu host compiler before kernel make.
* Full kernel compilation must succeed with the expanded container config.
  A final-ELF check inspects ARM64 branches for required helper callers, and the
  generated-assembly check must still prove all seventeen units are absent.
* Full ARM64 compilation, final-ELF checks and real encrypted I/O/boot are not yet
  verified at the time this document was prepared. Host tests do not establish
  disk-format compatibility, firmware interactions, power-loss behavior or
  container/Docker runtime success.

The workflow reports diagnostic success only after compilation and ELF checks,
then confirms the release gate prevented all `.img` output. It uploads debug
symbols and evidence under `Crypto-C-port-diagnostics`, not a flashable release.
