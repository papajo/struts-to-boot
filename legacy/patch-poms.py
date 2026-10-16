#!/usr/bin/env python3
"""Strip build plugins that only ever lived on the dead maven.mifos.org repo.

None of them affect the runnable app:
  mifos-pseudoloc-gen      generates pseudo-locale .properties for i18n testing
  mifos-settings-sanitizer writes a sample applicationConfiguration.custom.properties
  findbugs 2.3.2-SNAPSHOT  static analysis
Run inside the Docker build on a copy of the source; the submodule stays untouched.
"""
import re
import sys
from pathlib import Path

DEAD = ("mifos-pseudoloc-gen", "mifos-settings-sanitizer", "<version>2.3.2-SNAPSHOT</version>")
PLUGIN = re.compile(r"[ \t]*<plugin>(?:(?!<plugin>).)*?</plugin>[ \t]*\n?", re.S)

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
total = 0
for pom in sorted(root.rglob("pom.xml")):
    text = pom.read_text()
    new, n = PLUGIN.subn(lambda m: "" if any(d in m[0] for d in DEAD) else m[0], text)
    removed = text.count("<plugin>") - new.count("<plugin>")
    if removed:
        pom.write_text(new)
        total += removed
        print(f"{pom.relative_to(root)}: removed {removed} plugin(s)")
print(f"patch-poms: {total} plugin(s) removed")
