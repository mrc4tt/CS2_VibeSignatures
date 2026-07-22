import { expect, test } from '@playwright/test'

const run = {
  run_id: 'run-1', status: 'running', effective_status: 'running', is_stale: false,
  heartbeat_alive: true, gamever: '14141', agent: 'codex', created_at: '2026-07-13T00:00:00Z',
  started_at: null, updated_at: '2026-07-13T00:00:01Z', finished_at: null,
  current_stage_id: null, current_job_id: null, current_skill_id: null, last_event_id: '1-0',
  error_summary: null,
  progress: { total: 0, pending: 0, running: 0, succeeded: 0, failed: 0, skipped: 0, aborted: 0, completed: 0, percent: 0 },
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('cs2vibe.apiConnected:http://127.0.0.1:8000', 'true')
    localStorage.setItem('cs2vibe.language', 'zh-CN')
  })
  await page.route('**/api/v1/runs?**', (route) => route.fulfill({ json: { items: [run], offset: 0, next_offset: null, has_more: false } }))
  await page.route('**/api/v1/runs/run-1/snapshot', (route) => route.fulfill({ json: { run, graph: null, tasks: [], snapshot_event_id: '1-0' } }))
  await page.route('**/api/v1/runs/run-1/stream?**', (route) => route.fulfill({ contentType: 'text/event-stream', body: 'retry: 3000\n\n' }))
  await page.route('**/api/v1/runs/run-1', (route) => route.fulfill({ json: run }))
})

test('loads the run list from the runs route', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('link', { name: 'run-1' })).toBeVisible()
})

test('loads a run detail through the SPA fallback route', async ({ page }) => {
  await page.goto('/runs/run-1')
  await expect(page.getByText('run-1', { exact: true })).toBeVisible()
  await expect(page.getByText(/等待 ExecutionPlan 初始化/)).toBeVisible()
})

test('opens the static symbol browser without a Process API connection', async ({ page }) => {
  await page.goto('/symbols')
  await page.getByRole('button', { name: 'API 设置' }).click()
  await page.getByRole('button', { name: '断开当前连接' }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: '分析任务' }).click()
  await expect(page.getByRole('heading', { name: '连接本地进度 API' })).toBeVisible()
  await page.getByRole('tab', { name: '浏览符号' }).click()
  await expect(page.getByRole('heading', { name: '浏览符号' })).toBeVisible()
  await expect(page.getByLabel('游戏版本')).toHaveText(/14172/)
  await expect(page.getByText(/共 2942 条记录/)).toBeVisible()
})

test('switches the static application between supported languages', async ({ page }) => {
  await page.goto('/runs')
  await page.getByLabel('语言').click()
  await page.locator('.ant-select-dropdown').getByText('English', { exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analysis runs' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')

  await page.getByLabel('Language').click()
  await page.locator('.ant-select-dropdown').getByText('Traditional Chinese', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '分析任務' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
})

test('switches between graph and list views and opens task details', async ({ page }) => {
  const jobId = 'stage-0000-engine-windows'
  const taskId = `${jobId}/find-target`
  const task = {
    task_id: taskId, task_type: 'skill', name: 'find-target', stage_id: 'stage-0000-engine',
    job_id: jobId, status: 'running', phase: 'preprocessing', reason: null, attempt: null,
    max_attempts: null, started_at: null, updated_at: null, finished_at: null, message: null,
    error: null, payload: {}, event_type: 'task.status_changed', revision: 1,
  }
  const graph = {
    schema_version: 1,
    stages: [{ id: 'stage-0000-engine', stage_index: 0, module_name: 'engine' }],
    jobs: [{ id: jobId, stage_id: 'stage-0000-engine', stage_index: 0, module_name: 'engine', platform: 'windows', binary_path: 'bin/engine2.dll' }],
    nodes: [{ id: taskId, job_id: jobId, stage_id: 'stage-0000-engine', name: 'find-target', node_type: 'skill', order: 0, layer: 0, data: { expected_output: ['target.yaml'] } }],
    edges: [], warnings: [],
  }
  await page.unroute('**/api/v1/runs/run-1/snapshot')
  await page.route('**/api/v1/runs/run-1/snapshot', (route) => route.fulfill({ json: { run: { ...run, current_job_id: jobId, current_skill_id: taskId }, graph, tasks: [task], snapshot_event_id: '1-0' } }))
  await page.route('**/api/v1/runs/run-1/tasks/**', (route) => route.fulfill({ json: { ...task, dependencies: [], dependents: [] } }))
  await page.goto('/runs/run-1')
  await expect(page.getByText('思维导图')).toBeVisible()
  await expect(page.getByText('find-target', { exact: true }).first()).toBeVisible()
  await page.getByRole('tab', { name: '真实 DAG' }).click()
  await expect(page.locator('.graph-canvas')).toBeVisible()
  await page.getByRole('tab', { name: '任务列表' }).click()
  await page.getByRole('button', { name: 'find-target' }).click()
  await expect(page.getByText('任务详情')).toBeVisible()
  await expect(page.getByText(taskId, { exact: true })).toBeVisible()
})
