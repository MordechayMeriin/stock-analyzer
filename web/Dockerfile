# syntax=docker/dockerfile:1.7
# Web client image: Node build → nginx serving dist/. The API location is injected at
# container start (API_BASE_URL → /config.js), so one image works in every environment.
#
#   docker build -t stock-analyzer-web web/
#   docker run -p 8080:80 -e API_BASE_URL=https://api.example.com stock-analyzer-web
#
# Behind a TLS-intercepting proxy, pass its CA as a build secret (never stored in a layer):
#   docker build --secret id=ca,src=/path/to/ca.crt ...

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi && \
    npm ci --no-audit --no-fund
COPY . .
# No VITE_API_BASE_URL here: the runtime /config.js decides.
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/40-write-config.sh /docker-entrypoint.d/40-write-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
# Strip CRs in case the build context came from a CRLF checkout (see .gitattributes).
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-write-config.sh && \
    chmod +x /docker-entrypoint.d/40-write-config.sh
ENV API_BASE_URL=""
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
