#!/usr/bin/env python3
"""Check the final ARM64 ELF contains the C crypto helpers and live callers."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('vmlinux', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    with args.vmlinux.open('rb') as f:
        elf = ELFFile(f)
        assert elf['e_machine'] == 'EM_AARCH64' and elf.little_endian
        symtab = elf.get_section_by_name('.symtab')
        symbols = [s for s in symtab.iter_symbols()
                   if s['st_info']['type'] == 'STT_FUNC' and s['st_size']]
        targets = {s.name:s['st_value'] for s in symbols if s.name.startswith('hisi_inline_crypto_')}
        required = ['req_init','init_request','clone_bio','clone_request','advance','merge_allow']
        assert all('hisi_inline_crypto_'+n in targets for n in required), sorted(targets)
        byaddr = {v:k for k,v in targets.items()}
        callers = defaultdict(set)
        sections = {}
        for s in symbols:
            idx = s['st_shndx']
            if not isinstance(idx,int):
                continue
            if idx not in sections:
                sec = elf.get_section(idx)
                sections[idx] = (sec['sh_addr'],sec.data())
            start,data = sections[idx]
            offset = s['st_value']-start
            for delta in range(0,s['st_size']-3,4):
                instruction = struct.unpack_from('<I',data,offset+delta)[0]
                # Both BL calls and tail-call B instructions.
                if instruction & 0x7c000000 != 0x14000000:
                    continue
                imm = instruction & 0x03ffffff
                if imm & 0x02000000:
                    imm -= 0x04000000
                target = s['st_value']+delta+imm*4
                if target in byaddr:
                    callers[byaddr[target]].add(s.name)

        checks = {}
        groups = {
            'clone_bio': [('__bio_clone_fast',),('bio_clone_bioset',)],
            'advance': [('bio_advance',)],
            'req_init': [('blk_rq_init',),('blk_mq_rq_ctx_init','__blk_mq_alloc_request','blk_mq_alloc_request','blk_mq_alloc_request_hctx')],
            'init_request': [('blk_rq_bio_prep',),('blk_insert_cloned_request',)],
            'clone_request': [('__blk_rq_prep_clone','blk_rq_prep_clone')],
            'merge_allow': [('ll_back_merge_fn',),('ll_front_merge_fn',),('blk_rq_merge_ok',),('attempt_merge','attempt_back_merge','attempt_front_merge')],
        }
        for suffix, alternatives in groups.items():
            found = callers['hisi_inline_crypto_'+suffix]
            for group in alternatives:
                key = suffix+':'+','.join(group)
                checks[key] = any(any(n == p or n.startswith(p+'.') for p in group) for n in found)
        result = {'passed':all(checks.values()),'hardware_tested':False,
                  'checks':checks,'callers':{k:sorted(v) for k,v in callers.items()}}
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
        assert result['passed'], 'Missing required crypto helper call in linked ARM64 kernel'


if __name__ == '__main__':
    main()
