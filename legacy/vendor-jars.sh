#!/usr/bin/env bash
# Pull jars that exist on no live Maven repo out of the released Mifos 2.6.4 war (same codebase,
# HEAD is just past the 2.6.4 tag). Output: legacy/vendor/*.jar + manifest.tsv (file, g, a, v),
# installed into the local Maven repo by the Docker build. Run once on a host with internet.
set -euo pipefail
cd "$(dirname "$0")"
WAR_URL=https://downloads.sourceforge.net/project/mifos/mifos/2.6.4/mifos-v2.6.4-CF.war
WAR=.cache/mifos-v2.6.4-CF.war
mkdir -p vendor .cache
[[ -s $WAR ]] || curl -fL --retry 3 -o "$WAR" "$WAR_URL"
unzip -tq "$WAR" >/dev/null || { echo "bad war download: rm $WAR and retry" >&2; exit 1; }

# g a v  (jar inside WEB-INF/lib is matched as <a>-<v>.jar, else <a>*.jar)
NEED='
org.springframework.mobile spring-mobile-device 1.0.0.M3
org.apache jakarta-oro 20020329
struts struts-legacy 1.0
pentaho-library libbase 1.2.8
pentaho-library libdocbundle 1.2.8
pentaho-library libfonts 1.2.8
pentaho-library libformat 1.2.8
pentaho-library libformula 1.2.8
pentaho-library libloader 1.2.8
pentaho-library librepository 1.2.8
pentaho-library libserializer 1.2.8
pentaho-library libsparkline 1.2.8
pentaho-library libxml 1.2.8
pentaho-report-designer pentaho-reporting-engine-wizard-xul 3.9.1-GA
pentaho-reporting-engine pentaho-reporting-engine-classic-core 3.9.1-GA
pentaho-reporting-engine pentaho-reporting-engine-classic-extensions 3.9.1-GA
pentaho-reporting-engine pentaho-reporting-engine-wizard-core 3.9.1-GA
'
LIBS=$(unzip -Z1 "$WAR" 'WEB-INF/lib/*.jar')
: > vendor/manifest.tsv
missing=0
while read -r g a v; do
  [[ -z ${g:-} ]] && continue
  hit=$(grep -E "WEB-INF/lib/${a}-${v}\.jar$" <<<"$LIBS" || grep -E "WEB-INF/lib/${a}[-_.0-9A-Za-z]*\.jar$" <<<"$LIBS" | head -1 || true)
  if [[ -z $hit ]]; then echo "NOT IN WAR  $g:$a:$v"; missing=1; continue; fi
  unzip -joq "$WAR" "$hit" -d vendor
  printf '%s\t%s\t%s\t%s\n' "$(basename "$hit")" "$g" "$a" "$v" >> vendor/manifest.tsv
  echo "vendored    $g:$a:$v  <- $(basename "$hit")"
done <<<"$NEED"
echo "manifest: $(wc -l < vendor/manifest.tsv) jars"
exit $missing
