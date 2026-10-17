# Builds Mifos (Struts 1.2, Java 6-era) from source and runs it on Jetty.
# Build context: the mifos/head checkout (see legacy/README.md).
FROM maven:3.8.8-eclipse-temurin-8 AS build
WORKDIR /src
COPY . .
COPY --from=cfg settings.xml /root/.m2/settings.xml
COPY --from=cfg patch-poms.py /tmp/patch-poms.py
COPY --from=cfg patch-src.py /tmp/patch-src.py
# jars on no live repo, pulled from the released 2.6.4 war by legacy/vendor-jars.sh (run it first)
COPY --from=cfg vendor/ /vendor/
# maven.mifos.org is dead; settings.xml mirrors it to Central.
# 1. drop build-only plugins that existed only on that repo (pseudoloc, settings-sanitizer, findbugs SNAPSHOT)
# 2. install vendored jars (vendor/manifest.tsv) and the BIRT jars shipped in reporting-libs/;
#    stand in for the stripped settings-sanitizer output that the release assembly zips
# 3. build the war. Cache mount keeps downloaded deps across retries (bump id= to discard a poisoned cache);
#    -C fails on checksum mismatch so a repo serving HTML for jars is caught at download time.
ENV MVN="mvn -B -C -s /root/.m2/settings.xml -DskipTests -Dmaven.test.skip=true -Dmaven.compiler.source=1.8 -Dmaven.compiler.target=1.8"
RUN (command -v python3 >/dev/null || (apt-get update -qq && apt-get install -y -qq python3 >/dev/null)) && \
    python3 /tmp/patch-poms.py /src && python3 /tmp/patch-src.py /src
RUN --mount=type=cache,id=m2-v2,target=/root/.m2/repository \
    test -s /vendor/manifest.tsv || { echo "run legacy/vendor-jars.sh first" >&2; exit 1; }; \
    while IFS="$(printf '\t')" read -r f g a v; do \
      $MVN -q install:install-file -Dfile=/vendor/$f -DgroupId=$g -DartifactId=$a -Dversion=$v -Dpackaging=jar -DgeneratePom=true || exit 1; \
    done < /vendor/manifest.tsv && \
    $MVN -pl reporting-libs -am install && \
    mkdir -p appdomain/target && \
    cp appdomain/src/main/resources/org/mifos/config/resources/applicationConfiguration.default.properties \
       appdomain/target/applicationConfiguration.custom.properties && \
    $MVN -pl war -am package

FROM jetty:9.4-jre8
# plain webapp war (mifos.war is the self-executing variant with Jetty unpacked inside)
COPY --from=build /src/war/target/mifos-TEMP-nonexec.war /var/lib/jetty/webapps/mifos.war
# config dir must exist and be jetty-owned so the named volume inherits a writable dir
USER root
RUN mkdir -p /mifos-conf && chown jetty:jetty /mifos-conf
USER jetty
ENV JAVA_OPTIONS="-Xms1024m -Xmx1024m"
EXPOSE 8080
