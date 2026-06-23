# 帮你节省5分钟 — Docker 镜像
# 基于 Debian Bookworm Slim + Python 3.11

FROM python:3.11-slim-bookworm

# 避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 使用国内镜像源加速（清华源）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# 系统依赖：supervisor + curl + Chromium 系统库 + 中文字体 + 时区
# tkinter 已被 tkinter_stub 替代，不再需要 tk / xvfb / DISPLAY
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    wget \
    ca-certificates \
    tzdata \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Playwright 已迁移到云端，本地不再需要

# 工作目录
WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple --trusted-host mirrors.tuna.tsinghua.edu.cn -r requirements.txt

# 复制全部源码（.dockerignore 会过滤掉不需要的文件）
COPY . .

# 环境变量
ENV BROWSER=echo
ENV SUPERVISOR_MODE=1
ENV PYTHONUNBUFFERED=1

# 创建日志目录
RUN mkdir -p /app/application/portal/logs \
    /app/application/自动做测试报告 - cc/log \
    /app/application/all_in_one\ -\ cc/data

# 暴露端口
EXPOSE 5000 9000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# supervisord 作为入口
CMD ["supervisord", "-c", "/app/docker/supervisord.conf"]
