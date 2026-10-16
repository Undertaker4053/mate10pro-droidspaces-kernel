"""Prove fixed-layout generated Huawei .S objects were not built or linked."""
import json
from pathlib import Path
import re
import subprocess
import sys

from elftools.elf.elffile import ELFFile

image, source, build, output = map(Path, sys.argv[1:5])
tracked = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-r', '--name-only', 'HEAD']).decode().splitlines()
generated = []
for name in tracked:
    if not name.endswith('.S'):
        continue
    if re.search(rb'\.file[^\n]*\.c"', (source / name).read_bytes()):
        generated.append(name)
assert len(generated) == 17, 'Generated assembly inventory changed; review required'
objects = [str(build / (name[:-2] + '.o')) for name in generated
           if (build / (name[:-2] + '.o')).exists()]
linked = []
with image.open('rb') as stream:
    elf = ELFFile(stream)
    assert elf['e_machine'] == 'EM_AARCH64' and elf.has_dwarf_info()
    for cu in elf.get_dwarf_info().iter_CUs():
        name = cu.get_top_DIE().attributes.get('DW_AT_name')
        path = name.value.decode(errors='replace') if name else ''
        if '/jenkins/' in path and any(path.endswith('/' + item[:-2] + '.c') for item in generated):
            linked.append(path)
report = {'passed': not objects and not linked, 'generated_assembly_files': generated,
          'unexpected_objects': objects, 'unexpected_linked_units': linked,
          'scope': 'All 17 pinned Huawei C-to-assembly files must be absent from this fresh build. '
                   'Native architecture assembly is retained. This is not a boot or hardware test.'}
output.write_text(json.dumps(report, indent=2) + '\n')
assert report['passed'], 'Fixed-layout Huawei assembly remains in the full-feature build'
print('All 17 fixed-layout Huawei assembly files excluded from compilation and link', flush=True)
