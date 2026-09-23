# 前端镜像：多阶段构建（node 构建 → nginx 服务），照 fastapi/full-stack-fastapi-template 形态
FROM node:20-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
# 可选国内加速（同根 Dockerfile 的 ARG 约定；默认空 = npm 官方源）
ARG NPM_REGISTRY=
RUN npm ${NPM_REGISTRY:+--registry=$NPM_REGISTRY} ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# 实机验证 D30：busybox wget 优先解析 ::1，而 nginx listen 80 只绑 IPv4——
# 健康检查必须用 127.0.0.1（同 V2 教训：容器内 localhost≠127.0.0.1）
HEALTHCHECK --interval=30s --timeout=3s \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
