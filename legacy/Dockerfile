# Builds Mifos (Struts 1.2, Java 6-era) from source and runs it on Jetty.
# Build context: the mifos/head checkout (see legacy/README.md).
FROM maven:3.8.8-eclipse-temurin-8 AS build
WORKDIR /src
COPY . .
COPY --from=cfg settings.xml /root/.m2/settings.xml
COPY --from=cfg patch-poms.py /tmp/patch-poms.py
# maven.mifos.org is dead; settings.xml mirrors it to Central.
# 1. drop build-only plugins that existed only on that repo (pseudoloc, settings-sanitizer, findbugs SNAPSHOT)
# 2. install the BIRT jars shipped in reporting-libs/ (mifos-reporting depends on them)
# 3. build the war. Cache mount keeps downloaded deps across retries.
ENV MVN="mvn -B -s /root/.m2/settings.xml -DskipTests -Dmaven.compiler.source=1.8 -Dmaven.compiler.target=1.8"
RUN python3 /tmp/patch-poms.py /src || (apt-get update -qq && apt-get install -y -qq python3 >/dev/null && python3 /tmp/patch-poms.py /src)
RUN --mount=type=cache,target=/root/.m2/repository \
    $MVN -pl reporting-libs -am install && $MVN -pl war -am package

FROM jetty:9.4-jre8
COPY --from=build /src/war/target/*.war /var/lib/jetty/webapps/mifos.war
ENV JAVA_OPTIONS="-Xms1024m -Xmx1024m"
EXPOSE 8080
