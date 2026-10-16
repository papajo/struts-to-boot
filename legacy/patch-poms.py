#!/usr/bin/env python3
"""Strip build plugins that only ever lived on the dead maven.mifos.org repo.

None of them affect the runnable app:
  mifos-pseudoloc-gen      generates pseudo-locale .properties for i18n testing
  mifos-settings-sanitizer writes a sample applicationConfiguration.custom.properties
  findbugs 2.3.2-SNAPSHOT  static analysis
Also:
  - removes explicit test-scope <dependency> blocks outside dependencyManagement (build runs with
    -Dmaven.test.skip; strutstest is on no live repo)
  - yuicompressor-maven-plugin 0.9 (dead repo) -> 1.5.1 (Central), same config keys
Run inside the Docker build on a copy of the source; the submodule stays untouched.
"""
import re
import sys
from pathlib import Path

DEAD = ("mifos-pseudoloc-gen", "mifos-settings-sanitizer", "<version>2.3.2-SNAPSHOT</version>")
PLUGIN = re.compile(r"[ \t]*<plugin>(?:(?!<plugin>).)*?</plugin>[ \t]*\n?", re.S)
DEP = re.compile(r"[ \t]*<dependency>(?:(?!<dependency>).)*?</dependency>[ \t]*\n?", re.S)
YUI = re.compile(r"(<artifactId>yuicompressor-maven-plugin</artifactId>\s*<version>)0\.9(</version>)")

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
total = 0
for pom in sorted(root.rglob("pom.xml")):
    text = pom.read_text()
    new = PLUGIN.sub(lambda m: "" if any(d in m[0] for d in DEAD) else m[0], text)
    removed = text.count("<plugin>") - new.count("<plugin>")
    # strip test deps only outside <dependencyManagement> (managed entries supply versions to others)
    parts = re.split(r"(<dependencyManagement>.*?</dependencyManagement>)", new, flags=re.S)
    new = "".join(x if x.startswith("<dependencyManagement>")
                  else DEP.sub(lambda m: "" if "<scope>test</scope>" in m[0] else m[0], x) for x in parts)
    tdeps = text.count("<dependency>") - new.count("<dependency>")
    new, yui = YUI.subn(r"\g<1>1.5.1\2", new)
    if new != text:
        pom.write_text(new)
        total += removed
        print(f"{pom.relative_to(root)}: -{removed} plugin(s), -{tdeps} test dep(s){', yuicompressor 1.5.1' if yui else ''}")
print(f"patch-poms: {total} plugin(s) removed")
