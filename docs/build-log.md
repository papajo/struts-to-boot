# Legacy build log

| Date | Problem | Fix |
|---|---|---|
| 2026-10-16 | `mifos-pseudoloc-gen:1.0` not on Central (dead maven.mifos.org) | `legacy/patch-poms.py` strips it + `mifos-settings-sanitizer:0.0.1` + `findbugs-maven-plugin:2.3.2-SNAPSHOT` (build-only, 16 plugin blocks) during Docker build; BIRT jars installed from `reporting-libs/` first |
| 2026-10-16 | `spring-mobile-device:1.0.0.M3` (milestone, not on Central) + pentaho repo host `repo.orl.eng.hitachivantara.com` no longer resolves | `legacy/check-deps.py`: all 153 declared artifacts resolve; 19 only on Pentaho omni (`nexus.pentaho.org/content/groups/omni`) → settings.xml repo + pluginRepo |
| 2026-10-16 | 14 jars "error in opening zip file" after adding Pentaho omni repo | omni returns 200 + non-jar content; removed it, checker now requires POM `<project` + jar `PK` magic, Maven `-C` strict checksums, fresh cache id `m2-v2` |
| 2026-10-16 | 20 artifacts on no live repo (17 Pentaho/spring-mobile/oro/struts-legacy, strutstest, yuicompressor 0.9) | `legacy/vendor-jars.sh` extracts 17 jars from released `mifos-v2.6.4-CF.war` (SourceForge) → installed by Docker build; patch-poms strips explicit test deps (+ `-Dmaven.test.skip`) and bumps yuicompressor to 1.5.1 |
