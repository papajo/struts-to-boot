# Legacy build log

| Date | Problem | Fix |
|---|---|---|
| 2026-10-16 | `mifos-pseudoloc-gen:1.0` not on Central (dead maven.mifos.org) | `legacy/patch-poms.py` strips it + `mifos-settings-sanitizer:0.0.1` + `findbugs-maven-plugin:2.3.2-SNAPSHOT` (build-only, 16 plugin blocks) during Docker build; BIRT jars installed from `reporting-libs/` first |
| 2026-10-16 | `spring-mobile-device:1.0.0.M3` (milestone, not on Central) + pentaho repo host `repo.orl.eng.hitachivantara.com` no longer resolves | `legacy/check-deps.py`: all 153 declared artifacts resolve; 19 only on Pentaho omni (`nexus.pentaho.org/content/groups/omni`) → settings.xml repo + pluginRepo |
| 2026-10-16 | 14 jars "error in opening zip file" after adding Pentaho omni repo | omni returns 200 + non-jar content; removed it, checker now requires POM `<project` + jar `PK` magic, Maven `-C` strict checksums, fresh cache id `m2-v2` |
| 2026-10-16 | 20 artifacts on no live repo (17 Pentaho/spring-mobile/oro/struts-legacy, strutstest, yuicompressor 0.9) | `legacy/vendor-jars.sh` extracts 17 jars from released `mifos-v2.6.4-CF.war` (SourceForge) → installed by Docker build; patch-poms strips explicit test deps (+ `-Dmaven.test.skip`) and bumps yuicompressor to 1.5.1 |
| 2026-10-16 | `mifos-rest`: ajc "Invalid byte tag in constant pool: 18" (AspectJ 1.6.11 can't read Java 8 rt.jar) — 14/18 modules built | patch-poms: aspectj-maven-plugin 1.4 → 1.11 (ajc 1.8.13), aspectjrt/weaver 1.6.11 → 1.8.13, drop ajc test-compile |
| 2026-10-16 | `mifos-webapp`: native2ascii "Error starting Sun's native2ascii" — 15/18 modules built | patch-poms adds JDK `tools.jar` (system scope) as native2ascii plugin dependency |
| 2026-10-16 | `mifos-war`: release assembly wants `appdomain/target/applicationConfiguration.custom.properties` (output of stripped settings-sanitizer) — 17/18 built | Dockerfile copies the default properties there; runtime stage copies `mifos-TEMP-nonexec.war` (plain webapp) instead of `*.war` (two wars → COPY would fail) |
| 2026-10-16 | **Build green (18/18).** Container start: `bind: address already in use` on 8080 (oldbox) | host ports configurable: `MIFOS_PORT`, `MYSQL_PORT` (defaults 8080/3306) |
| 2026-10-16 | Webapp 503 at startup: `IllegalArgumentException: Invalid version number… greater than 255` in `com.ibm.icu.util.VersionInfo` (icu4j 4.0.1 can't parse Java 8u4xx) | patch-poms: icu4j 4.0.1 → 68.2 (fix landed in ICU 68 per BIRT dev list) |
