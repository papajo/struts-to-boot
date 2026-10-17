# Legacy: Mifos (Struts 1.2)

Source: https://github.com/mifos/head (last commit 2019-02-04). Pinned to `legacy-src/` as a git submodule.

## Run
```bash
git submodule update --init           # pulls mifos/head into legacy-src/
cd legacy && docker compose up --build
# http://localhost:18080/mifos  — login mifos / testmifos
```

## Known build risks (week-1 work)
- `maven.mifos.org` is dead. `settings.xml` mirrors it to Central. Mifos-internal modules build from source; third-party artifacts that only lived there need a replacement — log each in `docs/build-log.md`.
- `pentaho-*` reporting libs: extra repo configured in `settings.xml`. If still missing, exclude the `reporting` module from the build (outside the loan slice).
- `birt` libs (`${birt.libs.groupId}`): same — exclude if unresolvable.
- Java 6 source → compiled at 1.8. Fix anything that breaks; log it.
- Apple Silicon: MySQL 5.7 runs under amd64 emulation (slow but fine).

## Fallback
If the source build stalls past 3 days, record golden responses from a released `mifos.war` (SourceForge, Mifos 2.x) and keep building the slice from source in parallel.
