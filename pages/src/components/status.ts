const LABELS: Record<string, string> = {
  queued: '排队中',
  starting: '启动中',
  pending: '等待中',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  skipped: '跳过',
  aborted: '中止',
  stale: '失联',
}

export function statusLabel(status: string): string {
  return LABELS[status] || status
}
