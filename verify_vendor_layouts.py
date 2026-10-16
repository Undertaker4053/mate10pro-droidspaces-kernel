"""Reject ABI drift between generated Huawei assembly and rebuilt kernel C."""
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys

from elftools.elf.elffile import ELFFile

image, source, output = map(Path, sys.argv[1:4])
raw = image.read_bytes()
if image.suffix == '.gz':
    raw = gzip.decompress(raw)
elf = ELFFile(io.BytesIO(raw))
assert elf['e_machine'] == 'EM_AARCH64'
assert elf.has_dwarf_info(), 'Full DWARF is required for the ABI check'
dwarf = elf.get_dwarf_info()
symbols = elf.get_section_by_name('.symtab')
aranges = dwarf.get_aranges()
assert aranges is not None, 'Missing debug address ranges'
tracked = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-r', '--name-only', 'HEAD']).decode().splitlines()
assembly_paths = {name[:-2] + '.c' for name in tracked if name.endswith('.S')}
types = {'task_struct', 'thread_struct', 'mm_struct', 'page', 'sk_buff', 'sock',
         'sock_common', 'net_device', 'bio', 'request', 'request_queue',
         'file', 'inode', 'super_block', 'cred', 'signal_struct', 'nsproxy',
         'sched_entity', 'task_group', 'cgroup', 'cgroup_subsys_state', 'kmem_cache', 'user_struct'}


def structures(cu):
    found = {}
    for die in cu.iter_DIEs():
        name = die.attributes.get('DW_AT_name')
        size = die.attributes.get('DW_AT_byte_size')
        if die.tag != 'DW_TAG_structure_type' or name is None or size is None:
            continue
        name = name.value.decode(errors='replace')
        if name not in types:
            continue
        members = {}
        for member in die.iter_children():
            member_name = member.attributes.get('DW_AT_name')
            location = member.attributes.get('DW_AT_data_member_location')
            if member_name is None or location is None:
                continue
            fields = {'offset': location.value}
            for key in ['DW_AT_bit_size', 'DW_AT_bit_offset', 'DW_AT_data_bit_offset']:
                if key in member.attributes:
                    fields[key] = member.attributes[key].value
            members[member_name.value.decode(errors='replace')] = fields
        found[name] = {'size': size.value, 'members': members}
    return found


# Address ranges resolve these to newly compiled C, not the vendor .S units.
c_offsets = set()
for symbol_name in ['__alloc_skb', 'sock_init_data', 'blk_alloc_queue_node']:
    symbol = symbols.get_symbol_by_name(symbol_name)
    assert symbol, 'Missing canonical symbol ' + symbol_name
    offset = aranges.cu_offset_at_addr(symbol[0]['st_value'])
    assert offset is not None, 'No C debug unit for ' + symbol_name
    c_offsets.add(offset)
canonical = {}
assembly = []
for cu in dwarf.iter_CUs():
    name = cu.get_top_DIE().attributes.get('DW_AT_name')
    path = name.value.decode(errors='replace') if name else ''
    if cu.cu_offset in c_offsets:
        current = structures(cu)
        for key, value in current.items():
            if key in canonical:
                assert canonical[key] == value, 'Conflicting rebuilt C types: ' + key
            canonical[key] = value
    # Generated vendor units retain their original Jenkins source path.
    if '/jenkins/' in path and any(path.endswith('/' + candidate) for candidate in assembly_paths):
        assembly.append({'source': path.split('/kernel/')[-1], 'types': structures(cu)})
assert assembly, 'No generated Huawei assembly units found; refusing an empty check'
assert all(key in canonical for key in ['task_struct', 'sk_buff', 'sock', 'sock_common', 'page', 'bio', 'request_queue'])
differences = []
tail_extensions = []
comparisons = 0
for unit in assembly:
    for name, old in unit['types'].items():
        if name not in canonical:
            raise AssertionError('No rebuilt C definition for vendor type ' + name)
        new = canonical[name]
        comparisons += 1
        changed = {field: {'assembly': value, 'rebuilt': new['members'].get(field)}
                   for field, value in old['members'].items() if new['members'].get(field) != value}
        tail_extension = (name == 'user_struct' and not changed
                          and new['size'] == old['size'] + 8
                          and new['members'].get('mq_bytes', {}).get('offset') == old['size']
                          and set(new['members']) == set(old['members']) | {'mq_bytes'})
        if tail_extension:
            tail_extensions.append({'source': unit['source'], 'type': name,
                                    'old_size': old['size'], 'new_size': new['size'],
                                    'added_tail_member': 'mq_bytes', 'offset': old['size']})
        if (old['size'] != new['size'] and not tail_extension) or changed:
            differences.append({'source': unit['source'], 'type': name,
                                'assembly_size': old['size'], 'rebuilt_size': new['size'],
                                'changed_members': changed})
report = {'passed': not differences, 'assembly_units': len(assembly),
          'structure_comparisons': comparisons, 'canonical_types': canonical,
          'allowed_tail_extensions': tail_extensions,
          'differences': differences,
          'scope': 'Sizes and named member/bitfield offsets of selected shared kernel structures. '
                   'This check does not establish runtime safety or container functionality.'}
output.write_text(json.dumps(report, indent=2) + '\n')
print('Huawei assembly units:', len(assembly), 'structure comparisons:', comparisons, flush=True)
if differences:
    for item in differences:
        print('ABI MISMATCH:', item['source'], item['type'], item['assembly_size'], item['rebuilt_size'], flush=True)
    raise SystemExit('Vendor assembly ABI mismatch; image must not be delivered')
print('Vendor assembly ABI check passed', flush=True)
