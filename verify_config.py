"""Fail the build when Kconfig drops any requested DroidSpaces option."""
import json
import re
import sys
from pathlib import Path


def parse(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        enabled = re.match(r'(CONFIG_\w+)=(.*)$', line)
        disabled = re.match(r'# (CONFIG_\w+) is not set$', line)
        if enabled:
            result[enabled[1]] = enabled[2]
        elif disabled:
            result[disabled[1]] = 'n'
    return result


if __name__ == '__main__':
    actual = parse(sys.argv[1])
    expected = parse(sys.argv[2])
    failures = {key: {'expected': value, 'actual': actual.get(key, 'missing')}
                for key, value in expected.items()
                if actual.get(key, 'n') != value}
    print(json.dumps({'requested_options': len(expected), 'failures': failures}, indent=2))
    if failures:
        raise SystemExit('Required config values were dropped by Kconfig')
