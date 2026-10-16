# Legacy build log

| Date | Problem | Fix |
|---|---|---|
| 2026-10-16 | `mifos-pseudoloc-gen:1.0` not on Central (dead maven.mifos.org) | `legacy/patch-poms.py` strips it + `mifos-settings-sanitizer:0.0.1` + `findbugs-maven-plugin:2.3.2-SNAPSHOT` (build-only, 16 plugin blocks) during Docker build; BIRT jars installed from `reporting-libs/` first |
| 2026-10-16 | `spring-mobile-device:1.0.0.M3` (milestone, not on Central) + pentaho repo host `repo.orl.eng.hitachivantara.com` no longer resolves | `legacy/check-deps.py` probes every declared artifact against candidate repos; settings.xml updated from its output |
