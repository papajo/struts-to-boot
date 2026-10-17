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
  - AspectJ 1.6.11 can't read Java 8 class files ("Invalid byte tag in constant pool: 18"):
    aspectj-maven-plugin 1.4 -> 1.11 (ajc 1.8.13), aspectjrt/aspectjweaver 1.6.11 -> 1.8.13,
    and drop its test-compile goal (tests are skipped and their deps stripped)
  - native2ascii-maven-plugin 1.0-alpha-1 calls sun.tools.native2ascii.Main, which lives in the JDK's
    tools.jar and isn't on the plugin classpath: add tools.jar as a system-scoped plugin dependency
  - icu4j 4.0.1 crashes webapp startup on Java 8u256+ ("Version number may be negative or greater
    than 255": it parses java.version 1.8.0_4xx into a byte). Fixed in ICU 68 -> bump to 68.2
Run inside the Docker build on a copy of the source; the submodule stays untouched.
"""
import re
import sys
from pathlib import Path

DEAD = ("mifos-pseudoloc-gen", "mifos-settings-sanitizer", "<version>2.3.2-SNAPSHOT</version>")
PLUGIN = re.compile(r"[ \t]*<plugin>(?:(?!<plugin>).)*?</plugin>[ \t]*\n?", re.S)
DEP = re.compile(r"[ \t]*<dependency>(?:(?!<dependency>).)*?</dependency>[ \t]*\n?", re.S)
AJ_PLUGIN = re.compile(r"(<artifactId>aspectj-maven-plugin</artifactId>\s*<version>)1\.4(</version>)")
AJ_LIB = re.compile(r"(<artifactId>aspectj(?:rt|weaver)</artifactId>\s*<version>)1\.6\.11(</version>)")
AJ_TEST = re.compile(r"\s*<goal>test-compile</goal>")
N2A = re.compile(r"(<artifactId>native2ascii-maven-plugin</artifactId>\s*<version>1\.0-alpha-1</version>)(?!\s*<dependencies>)")
N2A_DEPS = ("\\1\n                <dependencies><dependency><groupId>com.sun</groupId><artifactId>tools</artifactId>"
            "<version>1.8</version><scope>system</scope><systemPath>${java.home}/../lib/tools.jar</systemPath>"
            "</dependency></dependencies>")
ICU = re.compile(r"(<artifactId>icu4j</artifactId>\s*<version>)4\.0\.1(</version>)")
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
    new, aj = AJ_PLUGIN.subn(r"\g<1>1.11\2", new)
    if aj:
        new = AJ_TEST.sub("", new)
    new, ajl = AJ_LIB.subn(r"\g<1>1.8.13\2", new)
    new, n2a = N2A.subn(N2A_DEPS, new)
    new, icu = ICU.subn(r"\g<1>68.2\2", new)
    if new != text:
        pom.write_text(new)
        total += removed
        print(f"{pom.relative_to(root)}: -{removed} plugin(s), -{tdeps} test dep(s){', yuicompressor 1.5.1' if yui else ''}{', aspectj plugin 1.11' if aj else ''}{f', aspectj libs 1.8.13 x{ajl}' if ajl else ''}{', native2ascii +tools.jar' if n2a else ''}{', icu4j 68.2' if icu else ''}")
print(f"patch-poms: {total} plugin(s) removed")
