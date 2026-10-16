#!/usr/bin/env python3
"""Compile the actual ported C helpers against a small host block-I/O model.

These tests exercise metadata semantics, not UFS hardware or real encrypted I/O.
The kernel build and final-ELF check are separate required checks.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

MODEL = r'''
#ifndef CRYPTO_TEST_MODEL
#define CRYPTO_TEST_MODEL
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t u64;
typedef uint64_t pgoff_t;
typedef uint64_t sector_t;
#define PAGE_SHIFT 12
#define PAGE_SIZE (1UL << PAGE_SHIFT)
#define BUG_ON(x) do { if (x) exit(86); } while (0)
__CONTEXT_TYPES__
struct bio {
 struct hisi_inline_crypto_bio hisi_bio;
 struct { unsigned bi_size; sector_t bi_sector; } bi_iter;
 unsigned offset, bi_vcnt;
 bool no_advance;
};
struct request_queue { bool hisi_inline_crypto; };
struct request {
 struct hisi_inline_crypto_req hisi_req;
 struct request_queue *q;
 struct bio *bio, *biotail;
 sector_t sector;
 unsigned bytes;
};
static inline bool bio_has_data(const struct bio *b) { return b->bi_iter.bi_size != 0; }
static inline bool bio_no_advance_iter(const struct bio *b) { return b->no_advance; }
#define bio_offset(b) ((b)->offset)
#define bio_sectors(b) ((b)->bi_iter.bi_size >> 9)
#define blk_rq_pos(r) ((r)->sector)
#define blk_rq_sectors(r) ((r)->bytes >> 9)
void blk_queue_set_inline_crypto_flag(struct request_queue *, bool);
int is_blk_queue_support_crypto(struct request_queue *);
#endif
'''

CASES = r'''
#include <linux/hisi-inline-crypto.h>
#include <assert.h>
static unsigned checks;
#define CHECK(x) do { checks++; if (!(x)) { \
 fprintf(stderr, "check %u failed at line %d: %s\n",checks,__LINE__,#x); return 1; } } while (0)

int main(int argc, char **argv)
{
 char key[64], other[64];
 struct request_queue q = {0};
 struct bio head = {0}, tail = {0}, incoming = {0}, clone = {0};
 struct request rq = {0}, copied = {0};
 head.hisi_bio = (struct hisi_inline_crypto_bio){key,64,3,100};
 head.bi_iter.bi_size = 4096; head.bi_iter.bi_sector = 800;
 tail = head; tail.hisi_bio.index = 101; tail.bi_iter.bi_sector = 808;
 incoming = head; incoming.hisi_bio.index = 102; incoming.bi_iter.bi_sector = 816;
 rq.q = &q; rq.bio = &head; rq.biotail = &tail; rq.sector = 800; rq.bytes = 8192;
#ifdef PORT_DISABLED_TEST
 rq.hisi_req.ci_key = key;
 hisi_inline_crypto_req_init(&rq);
 CHECK(rq.hisi_req.ci_key == key);
 CHECK(hisi_inline_crypto_merge_allow(&rq,&incoming));
 hisi_inline_crypto_clone_bio(&clone,&head);
 CHECK(clone.hisi_bio.ci_key == NULL);
 hisi_inline_crypto_advance(&head,4096);
 CHECK(head.hisi_bio.index == 100);
 printf("disabled/stub checks passed: %u\n",checks); return 0;
#else
 if (argc > 1 && !strcmp(argv[1],"invalid-key")) {
  head.hisi_bio.ci_key_len = 48;
  hisi_inline_crypto_init_request(&rq,&head); return 0;
 }
 if (argc > 1 && !strcmp(argv[1],"index-overflow")) {
  head.hisi_bio.index = (pgoff_t)-1;
  hisi_inline_crypto_advance(&head,4096); return 0;
 }
 CHECK(!is_blk_queue_support_crypto(&q));
 blk_queue_set_inline_crypto_flag(&q,true); CHECK(is_blk_queue_support_crypto(&q));
 blk_queue_set_inline_crypto_flag(&q,false); CHECK(!is_blk_queue_support_crypto(&q));
 /* Stacking queues must carry the key even before the lower UFS queue. */
 hisi_inline_crypto_init_request(&rq,&head);
 CHECK(rq.hisi_req.ci_key==key && rq.hisi_req.ci_key_len==64 && rq.hisi_req.ci_key_index==3);
 hisi_inline_crypto_clone_request(&copied,&rq);
 CHECK(!memcmp(&copied.hisi_req,&rq.hisi_req,sizeof(rq.hisi_req)));
 hisi_inline_crypto_req_init(&copied);
 CHECK(copied.hisi_req.ci_key==NULL && copied.hisi_req.ci_key_len==0 && copied.hisi_req.ci_key_index==-1);
 hisi_inline_crypto_clone_bio(&clone,&head);
 CHECK(clone.hisi_bio.ci_key==key && clone.hisi_bio.index==100);
 /* The real clone API copies its iterator before calling the helper. */
 clone.bi_iter=head.bi_iter; clone.offset=head.offset;
 /* Back merge, front merge, key mismatch, length mismatch, keyslot mismatch. */
 CHECK(hisi_inline_crypto_merge_allow(&rq,&incoming));
 tail.bi_vcnt=999; CHECK(hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.index=103; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.index=102; incoming.hisi_bio.ci_key=other;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); incoming.hisi_bio.ci_key=key;
 incoming.hisi_bio.ci_key_len=48; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.ci_key_len=64; incoming.hisi_bio.ci_key_index=4;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); incoming.hisi_bio.ci_key_index=3;
 incoming.hisi_bio.ci_key=NULL; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.ci_key=key; rq.hisi_req.ci_key=NULL;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); rq.hisi_req.ci_key=key;
 incoming.bi_iter.bi_sector=792; incoming.hisi_bio.index=99;
 CHECK(hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.index=98; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.hisi_bio.index=99; incoming.bi_iter.bi_sector=700;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.bi_iter.bi_sector=816; incoming.hisi_bio.index=102;
 incoming.bi_iter.bi_size=512; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming));
 incoming.bi_iter.bi_size=4096; tail.offset=512;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); tail.offset=0;
 rq.bio=NULL; CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); rq.bio=&head;
 tail.hisi_bio.index=(pgoff_t)-1; incoming.hisi_bio.index=0;
 CHECK(!hisi_inline_crypto_merge_allow(&rq,&incoming)); tail.hisi_bio.index=101;
 /* Clone, split/trim offsets, partial completion, end-of-BIO, no-advance ops. */
 hisi_inline_crypto_advance(&clone,512); CHECK(clone.hisi_bio.index==100);
 clone.offset=512; hisi_inline_crypto_advance(&clone,3584); CHECK(clone.hisi_bio.index==101);
 clone.offset=0; hisi_inline_crypto_advance(&clone,8192); CHECK(clone.hisi_bio.index==103);
 hisi_inline_crypto_advance(&clone,0); CHECK(clone.hisi_bio.index==103);
 clone.no_advance=true; hisi_inline_crypto_advance(&clone,4096); CHECK(clone.hisi_bio.index==103);
 clone.no_advance=false; clone.bi_iter.bi_size=0;
 hisi_inline_crypto_advance(&clone,4096); CHECK(clone.hisi_bio.index==103);
 /* Plain I/O clears recycled keys; crypto restrictions do not affect it. */
 head.hisi_bio.ci_key=NULL; head.hisi_bio.ci_key_len=0; head.hisi_bio.index=0;
 hisi_inline_crypto_init_request(&rq,&head);
 CHECK(!rq.hisi_req.ci_key && rq.hisi_req.ci_key_len==0 && rq.hisi_req.ci_key_index==-1);
 incoming.hisi_bio.ci_key=NULL; incoming.bi_iter.bi_size=512;
 CHECK(hisi_inline_crypto_merge_allow(&rq,&incoming));
 hisi_inline_crypto_clone_bio(&clone,&head); CHECK(clone.hisi_bio.ci_key==NULL);
 hisi_inline_crypto_advance(&clone,4096); CHECK(clone.hisi_bio.index==0);
 hisi_inline_crypto_init_request(&rq,NULL); CHECK(!rq.hisi_req.ci_key);
 printf("crypto semantic checks passed: %u\n",checks);
 return 0;
#endif
}
'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('kernel', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--zig', type=Path, help='Optional Windows-native host C compiler')
    args = ap.parse_args()
    kernel = args.kernel.resolve()
    types = (kernel/'include/linux/blk_types.h').read_text()
    contexts = '\n'.join(re.findall(r'struct hisi_inline_crypto_(?:bio|req) \{.*?\n\};', types, re.S))
    assert contexts.count('struct hisi_inline_crypto_') == 2
    results = []
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except ImportError:
        pass
    with tempfile.TemporaryDirectory(prefix='hisi-crypto-test-') as tmp:
        tmp = Path(tmp)
        inc = tmp/'include/linux'
        inc.mkdir(parents=True)
        (inc/'model.h').write_text(MODEL.replace('__CONTEXT_TYPES__', contexts))
        for header in ['bio.h', 'blkdev.h', 'kernel.h']:
            (inc/header).write_text('#include "model.h"\n')
        (tmp/'cases.c').write_text(CASES)
        for mode, defines in [
            ('c-fallback', ['-DCONFIG_SCSI_UFS_INLINE_CRYPTO']),
            ('stock-hisi-stubs', ['-DCONFIG_SCSI_UFS_INLINE_CRYPTO','-DCONFIG_HISI_BLK','-DPORT_DISABLED_TEST']),
            ('crypto-off-stubs', ['-DPORT_DISABLED_TEST']),
        ]:
            binary = tmp/(mode+'.exe' if os.name == 'nt' else mode)
            compiler = [str(args.zig),'cc'] if args.zig else [os.environ.get('HOSTCC','gcc')]
            cmd = [*compiler, '-std=gnu99', '-O2', '-Wall', '-Werror',
                   '-Wno-unused-variable', '-I'+str(tmp/'include'), '-I'+str(kernel/'include'),
                   *defines, str(tmp/'cases.c'), str(kernel/'block/hisi-inline-crypto.c'), '-o',str(binary)]
            subprocess.run(cmd, check=True)
            p = subprocess.run([str(binary)], check=True, text=True, stdout=subprocess.PIPE)
            print(mode+': '+p.stdout.strip())
            results.append({'mode':mode,'passed':True,'output':p.stdout.strip()})
            if mode == 'c-fallback':
                for invalid in ['invalid-key','index-overflow']:
                    p = subprocess.run([str(binary),invalid], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    assert p.returncode == 86, invalid+' must trigger the modeled BUG_ON'
                    results.append({'mode':invalid,'passed':True,'rejected':True})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'passed':True,'hardware_tested':False,'results':results},indent=2)+'\n')

if __name__ == '__main__':
    main()
