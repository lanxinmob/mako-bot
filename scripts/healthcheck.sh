#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# mako-bot 每日健康检查脚本
#
# 检查项:
#   1. systemd 服务状态
#   2. HTTP 端口可达性
#   3. 进程内存占用（对比告警阈值）
#   4. 内核 OOM 日志（近 24 小时）
#
# 自动修复: 服务异常时尝试重启，无法修复则记录告警。
# 日志输出: logs/healthcheck.log
# ---------------------------------------------------------------------------
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
readonly LOG_FILE="${PROJECT_DIR}/logs/healthcheck.log"
readonly SERVICE_NAME="mako-bot.service"
readonly HTTP_HOST="${MAKO_HOST:-127.0.0.1}"
readonly HTTP_PORT="${MAKO_PORT:-8080}"
readonly MEM_WARN_MB=600
readonly MEM_CRIT_MB=800

# ── 确保日志目录存在 ────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"

# ── 日志函数 ────────────────────────────────────────────────────────────────
log() {
    local level="$1"; shift
    local msg="$*"
    printf "[%s] [%s] %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$msg" | tee -a "$LOG_FILE"
}

log_separator() {
    echo "──────────────────────────────────────────────────────" >> "$LOG_FILE"
}

# ── 1. systemd 服务状态 ─────────────────────────────────────────────────────
check_service() {
    log INFO "检查 systemd 服务: ${SERVICE_NAME}"

    if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
        log ERROR "服务未运行: ${SERVICE_NAME}"
        return 1
    fi

    local status
    status=$(systemctl is-active "${SERVICE_NAME}")
    log INFO "服务状态: ${status}"

    # 检查是否有失败的 restart 循环
    local nrestarts
    nrestarts=$(systemctl show "${SERVICE_NAME}" -p NRestarts 2>/dev/null | cut -d= -f2)
    if [[ -n "${nrestarts}" && "${nrestarts}" -gt 3 ]]; then
        log WARN "服务近期重启 ${nrestarts} 次，可能存在反复崩溃"
    fi
    return 0
}

# ── 2. HTTP 端点可达性 ─────────────────────────────────────────────────────
check_http() {
    log INFO "检查 HTTP 端点: ${HTTP_HOST}:${HTTP_PORT}"

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        "http://${HTTP_HOST}:${HTTP_PORT}/" 2>/dev/null || echo "000")

    if [[ "${http_code}" == "000" ]]; then
        log ERROR "HTTP 端点不可达: ${HTTP_HOST}:${HTTP_PORT}"
        return 1
    fi

    log INFO "HTTP 响应码: ${http_code}"
    return 0
}

# ── 3. 内存检查 ─────────────────────────────────────────────────────────────
check_memory() {
    log INFO "检查进程内存占用"

    local pid
    pid=$(systemctl show "${SERVICE_NAME}" -p MainPID 2>/dev/null | cut -d= -f2)
    if [[ -z "${pid}" || "${pid}" == "0" ]]; then
        log WARN "无法获取主进程 PID"
        return 0
    fi

    local rss_kb rss_mb
    rss_kb=$(awk '/VmRSS/{print $2}' "/proc/${pid}/status" 2>/dev/null || echo "0")
    rss_mb=$((rss_kb / 1024))

    log INFO "进程 PID=${pid} RSS=${rss_mb}MB"

    if [[ "${rss_mb}" -ge "${MEM_CRIT_MB}" ]]; then
        log ERROR "内存严重超标: ${rss_mb}MB >= ${MEM_CRIT_MB}MB"
        return 2
    elif [[ "${rss_mb}" -ge "${MEM_WARN_MB}" ]]; then
        log WARN "内存偏高: ${rss_mb}MB >= ${MEM_WARN_MB}MB"
        return 1
    fi
    return 0
}

# ── 4. OOM 日志扫描 ─────────────────────────────────────────────────────────
check_oom() {
    log INFO "扫描近 24 小时 OOM 事件"

    local oom_lines
    oom_lines=$(journalctl -k --since "24 hours ago" --no-pager 2>/dev/null \
        | grep -i "oom-kill.*mako\|Out of memory.*mako\|invoked oom-killer" || true)

    if [[ -n "${oom_lines}" ]]; then
        log ERROR "检测到 OOM 事件:"
        echo "${oom_lines}" | while read -r line; do
            log ERROR "  ${line}"
        done
        return 1
    fi

    log INFO "无 OOM 事件"
    return 0
}

# ── 主流程 ──────────────────────────────────────────────────────────────────
main() {
    log_separator
    log INFO "========== mako-bot 健康检查开始 =========="

    local failures=0
    local mem_status=0

    check_service   || ((failures++))
    check_http      || ((failures++))
    check_memory    ; mem_status=$?
    check_oom       || ((failures++))

    # ── 自动修复 ────────────────────────────────────────────────────────────
    if [[ "${failures}" -gt 0 || "${mem_status}" -eq 2 ]]; then
        log WARN "检测到 ${failures} 项异常 (内存级别=${mem_status})，尝试重启服务..."

        if systemctl restart "${SERVICE_NAME}"; then
            log INFO "服务重启成功"
            sleep 5

            # 重启后再验证
            if systemctl is-active --quiet "${SERVICE_NAME}"; then
                log INFO "重启后服务已恢复运行"
            else
                log ERROR "重启后服务仍未运行！请人工介入"
            fi
        else
            log ERROR "服务重启失败！请人工介入"
        fi
    else
        log INFO "所有检查通过，服务运行正常"
    fi

    log INFO "========== mako-bot 健康检查结束 =========="
}

main "$@"
