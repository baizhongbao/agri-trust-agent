# ============================================================
#  后端镜像
#
#  刻意固定 Python 3.11：跨机一致性优先。
#  无论宿主机是 3.13 还是别的版本，容器内始终是 3.11，
#  避免不同机器的 wheel 可用性差异导致"我这里能跑"的问题。
# ============================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PROJECT_ROOT=/app

WORKDIR /app

# build-essential：纯 Python wheel 缺失时的编译兜底
# curl：容器健康检查使用
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 国内加速；可通过 --build-arg 覆盖为官方源
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# 是否需要本地 Embedding / Reranker（torch 体积较大）
ARG INSTALL_ML=true

COPY requirements.txt requirements-ml.txt ./

RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt \
    && if [ "$INSTALL_ML" = "true" ]; then \
           pip install --no-cache-dir -i ${PIP_INDEX} -r requirements-ml.txt; \
       fi

COPY app ./app

# 非 root 运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
