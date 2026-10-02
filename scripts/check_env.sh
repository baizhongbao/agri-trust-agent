#!/usr/bin/env bash
# ============================================================
#  订单农业可信性 Agent - Linux 环境体检
#
#  用途：确认"Linux 作为主力开发机"是否成立
#  特性：只读检测，不做任何修改
#  用法：bash scripts/check_env.sh
# ============================================================
set -u

line() { printf '\n########## %s ##########\n' "$1"; }

line "1. 发行版与内核"
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "  distro : ${PRETTY_NAME:-unknown}"
fi
echo "  kernel : $(uname -r)"
echo "  arch   : $(uname -m)"

line "2. 硬件资源"
echo "  CPU    : $(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ //')"
echo "  cores  : $(nproc 2>/dev/null)"
echo "  RAM    : $(free -h 2>/dev/null | awk '/^Mem:/ {print $2" total / "$7" available"}')"

line "3. GPU（决定能否本地跑 Embedding / Reranker）"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader | sed 's/^/  /'
    echo "  CUDA 驱动支持上限: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
    if command -v nvcc >/dev/null 2>&1; then
        echo "  nvcc   : $(nvcc --version | tail -n1 | sed 's/^ *//')"
    else
        echo "  nvcc   : 未安装（pip 版 torch 自带运行时，通常无需单独装）"
    fi
    ls -d /usr/local/cuda* 2>/dev/null | sed 's/^/  toolkit: /'
else
    echo "  [MISSING] 未检测到 NVIDIA 驱动 -> 本地模型只能用 CPU，估算慢 10~30 倍"
fi

line "4. 磁盘空间"
df -h 2>/dev/null | grep -E '^(Filesystem|/dev)' | sed 's/^/  /'

line "5. 工具链"
for c in git python3 pip3 node npm pnpm docker curl make gcc; do
    if command -v "$c" >/dev/null 2>&1; then
        printf '  [OK]      %-8s %s\n' "$c" "$("$c" --version 2>&1 | head -n1)"
    else
        printf '  [MISSING] %s\n' "$c"
    fi
done

line "6. Python 多版本可用性"
for p in python3 python3.10 python3.11 python3.12 python3.13; do
    if command -v "$p" >/dev/null 2>&1; then
        printf '  %-12s %s\n' "$p" "$("$p" --version 2>&1)"
    fi
done
if command -v python3 >/dev/null 2>&1; then
    echo "  venv    : $(python3 -c 'import venv; print("available")' 2>&1)"
    echo "  pip idx : $(pip3 config get global.index-url 2>&1 | head -n1)"
    echo "  torch   : $(python3 -c 'import torch; print(torch.__version__, "cuda:", torch.cuda.is_available())' 2>&1 | head -n1)"
fi

line "7. Docker 状态"
if command -v docker >/dev/null 2>&1; then
    echo "  client : $(docker --version 2>&1)"
    docker info --format '  server : {{.ServerVersion}} / OSType={{.OSType}} / root={{.DockerRootDir}}' 2>&1 | head -n2 | sed 's/^/  /'
    echo "  compose: $(docker compose version 2>&1 | head -n1)"
    echo "  runtimes: $(docker info --format '{{json .Runtimes}}' 2>/dev/null | head -c 240)"
    if [ -f "$HOME/.docker/daemon.json" ]; then
        echo "  daemon.json:"
        sed 's/^/    /' "$HOME/.docker/daemon.json"
    else
        echo "  daemon.json: 不存在 -> 未配置镜像加速"
    fi
    echo "  当前用户是否在 docker 组: $(id -nG 2>/dev/null | tr ' ' '\n' | grep -cx docker)"
else
    echo "  docker 未安装"
fi

line "8. 网络连通性"
check_url() {
    local url="$1" code
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 6 -I "$url" 2>/dev/null)
    if [ -n "${code:-}" ] && [ "$code" != "000" ]; then
        printf '  %-44s reachable (%s)\n' "$url" "$code"
    else
        printf '  %-44s UNREACHABLE\n' "$url"
    fi
}
for u in \
    https://www.huaweicloud.com \
    https://pypi.tuna.tsinghua.edu.cn/simple/ \
    https://hf-mirror.com \
    https://registry.npmmirror.com \
    https://registry-1.docker.io/v2/
do
    check_url "$u"
done
echo "  http_proxy =${http_proxy:-<未设置>}"
echo "  https_proxy=${https_proxy:-<未设置>}"
echo "  no_proxy   =${no_proxy:-<未设置>}"

line "9. 凭证与环境变量"
for v in HUAWEI_CLOUD_AK HUAWEI_CLOUD_SK HUAWEI_CLOUD_REGION \
         MODELARTS_API_KEY PANGU_API_KEY \
         HF_ENDPOINT HF_HOME; do
    if [ -n "${!v:-}" ]; then
        printf '  %-22s : 已配置\n' "$v"
    else
        printf '  %-22s : 未配置\n' "$v"
    fi
done

line "10. 桌面环境（判断是否适合做前端开发）"
echo "  DISPLAY=${DISPLAY:-<未设置>}"
echo "  WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<未设置>}"
echo "  session type: ${XDG_SESSION_TYPE:-<未知>}"

line "DONE"
