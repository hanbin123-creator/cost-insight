# 创灵境成本分析 · 应用镜像（FastAPI + LibreOffice PDF 渲染）
# LibreOffice 安装层照 gotenberg/gotenberg 行业标准做法：官方 apt 包 +
# --no-install-recommends 控体积 + 中文字体 + fc-cache 刷新字体缓存。
# 与 gotenberg 的差异：我们把 LibreOffice 与 FastAPI 放同一容器（render.py 本机
# subprocess 调 soffice），省去跨容器 HTTP 转换服务——少一个故障面。
FROM python:3.12-slim

# 可选国内加速（实机验证 D28：本机到 deb.debian.org/pypi 仅数十 KB/s）。
# 默认空 = 全部上游源，评委/CI 零感知；国内构建慢时才显式传入：
#   docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com \
#       --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG APT_MIRROR=
ARG PIP_INDEX_URL=
RUN if [ -n "$APT_MIRROR" ]; then \
        for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
            [ -f "$f" ] && sed -i "s|deb.debian.org|$APT_MIRROR|g" "$f"; \
        done; \
    fi

# --- LibreOffice 层（docx→pdf 只需 writer 组件；fonts-noto-cjk 保底中文渲染） ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-core \
        fontconfig fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层单独 COPY：源码改动不破坏 pip 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} -r requirements.txt

# 项目自带 NotoSansSC 同时注册进系统字体目录（matplotlib 嵌图与 LibreOffice 共用）
COPY assets/fonts/ /usr/share/fonts/truetype/noto-sc/
RUN fc-cache -f

# 应用代码与烘焙产物（模型 .ready 已验证 → 运行时强制离线，零下载零联网）
# config/ 含占位符映射与 RPA 名册；assets/ 含报告模板与字体；data/kb/ 为索引三件套
COPY app/ app/
COPY assets/ assets/
COPY models/ models/
COPY config/ config/
COPY data/kb/ data/kb/
COPY scripts/docker_entrypoint.sh /docker_entrypoint.sh
RUN chmod +x /docker_entrypoint.sh

# 运行环境：离线强制 + 生产向量后端（compose 覆盖）
ENV HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    COST_INSIGHT_DATA_DIR=/data-source

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/products', timeout=4)"

CMD ["/docker_entrypoint.sh"]
