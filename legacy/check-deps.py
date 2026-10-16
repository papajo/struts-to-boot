#!/usr/bin/env python3
"""Find every declared dependency/plugin the Mifos build needs that no reachable repo serves.

Run on a machine with internet (not inside Docker):  python3 legacy/check-deps.py
Prints, per artifact, which repo has it; lists the ones nobody has at the end.
Direct declarations only (transitives surface on the next build, if any).
"""
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "legacy-src"
NS = "{http://maven.apache.org/POM/4.0.0}"
REPOS = {
    "central": "https://repo.maven.apache.org/maven2/",
    "spring-milestone": "https://repo.spring.io/milestone/",
    "pentaho-omni": "https://nexus.pentaho.org/content/groups/omni/",
    "pentaho-public": "https://public.nexus.pentaho.org/repository/omni/",
    "hv-pnt-mvn": "https://one.hitachivantara.com/artifactory/pnt-mvn/",
    "jboss": "https://repository.jboss.org/nexus/content/groups/public/",
    "scijava": "https://maven.scijava.org/content/groups/public/",
    "jaspersoft": "https://jaspersoft.jfrog.io/artifactory/third-party-ce-artifacts/",
}
DEAD = ("mifos-pseudoloc-gen", "mifos-settings-sanitizer", "lifecycle-mapping")  # stripped by patch-poms.py

props, managed, reactor, wanted = {}, {}, set(), set()
poms = [p for p in ROOT.rglob("pom.xml") if "/target/" not in str(p)]
trees = {p: ET.parse(p).getroot() for p in poms}
for p, r in trees.items():
    reactor.add(r.findtext(NS + "artifactId"))
    for pr in r.findall(NS + "properties/*"):
        props.setdefault(pr.tag.replace(NS, ""), (pr.text or "").strip())
    props.setdefault("project.version", r.findtext(NS + "version") or r.findtext(f"{NS}parent/{NS}version"))


def sub(s):
    for _ in range(5):
        s = re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m[1], m[0]), s or "")
    return s


for r in trees.values():
    for d in r.iter(NS + "dependency"):
        g, a, v = sub(d.findtext(NS + "groupId")), sub(d.findtext(NS + "artifactId")), sub(d.findtext(NS + "version"))
        if v:
            managed.setdefault((g, a), v)
for r in trees.values():
    for kind in ("dependency", "plugin", "extension"):
        for d in r.iter(NS + kind):
            g = sub(d.findtext(NS + "groupId") or "org.apache.maven.plugins")
            a = sub(d.findtext(NS + "artifactId"))
            v = sub(d.findtext(NS + "version")) or managed.get((g, a), "")
            if a in reactor or a in DEAD or v.endswith("2.3.2-SNAPSHOT") or not v or "${" in v or g.startswith("org.mifos.birtlibs"):
                continue
            if d.findtext(NS + "scope") == "system":
                continue
            wanted.add((g, a, v))


def fetch(url: str, n: int) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Apache-Maven/3.8", "Range": f"bytes=0-{n}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read(n)
    except Exception:
        return None


def check(gav):
    """A repo 'has' an artifact only if it serves a real POM *and* a real jar (zip magic).
    Some dead repos answer 200 with an HTML notice for every path."""
    g, a, v = gav
    base_path = f"{g.replace('.', '/')}/{a}/{v}/{a}-{v}"
    for name, base in REPOS.items():
        pom = fetch(base + base_path + ".pom", 512)
        if not pom or b"<project" not in pom:
            continue
        jar = fetch(base + base_path + ".jar", 4)
        if jar and jar.startswith(b"PK"):
            return gav, name
        if b"<packaging>pom</packaging>" in (fetch(base + base_path + ".pom", 20000) or b""):
            return gav, name
    return gav, None


with ThreadPoolExecutor(16) as ex:
    results = sorted(ex.map(check, wanted))
missing = [gav for gav, repo in results if repo is None]
for gav, repo in results:
    if repo != "central":
        print(f"{repo or 'MISSING':16} {':'.join(gav)}")
print(f"\n{len(results)} artifacts checked, {len(results) - len(missing)} found, {len(missing)} missing")
sys.exit(1 if missing else 0)
