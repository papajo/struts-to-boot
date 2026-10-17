#!/usr/bin/env python3
"""Runtime-compat source patches for Mifos on Jetty 9.4 (applied to a copy inside the Docker build).

Each patch is an exact (file, old, new) replacement and fails loudly if the source moved.
Only environment-compat fixes belong here; never change business behaviour.

1. UrlHelper.constructCurrentPageUrl: deleteCharAt(servletPath.indexOf('/')) throws
   StringIndexOutOfBounds when the originating servlet path has no '/' (Jetty 9.4 hands the
   Spring "cheetah" servlet such paths on Struts->FTL forwards). Every loan page and the error
   page itself died with a 500 via BackUrlInterceptor. Guard the delete (2 sites in the file).
"""
import sys
from pathlib import Path

PATCHES = [
    ("userInterface/src/main/java/org/mifos/ui/core/controller/util/helpers/UrlHelper.java",
     """        StringBuilder url = new StringBuilder(originatingServletPath).append("?").append(originatingQueryString).deleteCharAt(originatingServletPath.indexOf('/'));""",
     """        StringBuilder url = new StringBuilder(originatingServletPath).append("?").append(originatingQueryString);
        int slash = originatingServletPath.indexOf('/');   // struts-to-boot: Jetty 9.4 compat
        if (slash >= 0) {
            url.deleteCharAt(slash);
        }"""),
]

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
for rel, old, new in PATCHES:
    p = root / rel
    s = p.read_text()
    if new in s:
        print(f"patch-src: already applied {rel}")
        continue
    n = s.count(old)
    if n == 0:
        raise SystemExit(f"patch-src: anchor not found in {rel}")
    p.write_text(s.replace(old, new))
    print(f"patch-src: patched {rel} ({n} site{'s' if n > 1 else ''})")
