FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# 【关键修复】声明为非交互式环境，防止 tzdata 安装时卡住弹窗
ENV DEBIAN_FRONTEND=noninteractive
# 提前设置好时区，tzdata 安装时会直接读取这个环境变量
ENV TZ=Asia/Shanghai

RUN apt-get update && \
    apt-get install -y dumb-init tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 使用 dumb-init 接管 PID 1 回收 Playwright 产生的僵尸进程
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# 启动 Uvicorn，绑定 Render 提供的端口，默认 8000
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
