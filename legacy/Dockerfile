# Builds Mifos (Struts 1.2, Java 6-era) from source and runs it on Jetty.
# Build context: the mifos/head checkout (see legacy/README.md).
FROM maven:3.8.8-eclipse-temurin-8 AS build
WORKDIR /src
COPY . .
COPY --from=cfg settings.xml /root/.m2/settings.xml
# maven.mifos.org is dead; settings.xml mirrors it to Central. Expect missing
# artifacts on first run — resolve each into legacy/m2-overrides/ (see README).
RUN mvn -B -s /root/.m2/settings.xml -DskipTests -Dmaven.compiler.source=1.8 -Dmaven.compiler.target=1.8 \
      -pl war -am package

FROM jetty:9.4-jre8
COPY --from=build /src/war/target/*.war /var/lib/jetty/webapps/mifos.war
ENV JAVA_OPTIONS="-Xms1024m -Xmx1024m"
EXPOSE 8080
