import re

def to_single_dash(filename):
    'https://packaging.python.org/en/latest/specifications/version-specifiers/#version-specifiers'

    # selenium-2.0-dev-9429.tar.gz
    m = re.search(r'-[0-9].*-', filename)
    if m:
        s2 = filename[m.start() + 1:]
        # 2.0-dev-9429.tar.gz
        s2 = s2.replace('-dev-', '.dev')
        # 2.0.dev9429.tar.gz
        s2 = s2.replace('-', '.')
        filename = filename[:m.start() + 1] + s2
    return filename
    # selenium-2.0.dev9429.tar.gz
