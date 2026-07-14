import { Card, Space, Spin, Switch, Tabs, Typography } from 'antd'
import { lazy, Suspense } from 'react'
import type { TaskView } from '../../api/types'
import type { GraphFilters, VisualGraph } from '../../graph/model'
import { TaskTable } from './TaskTable'

type ViewMode = 'mindmap' | 'dag' | 'list'
const GraphCanvas = lazy(() => import('../../graph/GraphCanvas').then((module) => ({ default: module.GraphCanvas })))

interface Props {
  view: ViewMode
  mindMap: VisualGraph
  dag: VisualGraph
  tasks: TaskView[]
  filters: GraphFilters
  selectedTask?: string
  showStageOrder: boolean
  onView(view: string): void
  onSelect(id: string): void
  onToggleExpand(id: string): void
  onShowStageOrder(value: boolean): void
}

function graphFallback() {
  return <div className="page-spinner"><Spin /></div>
}

function MindMapTab({ props }: { props: Props }) {
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Text type="secondary">默认展开全部 Skill 子代；双击有后代的节点可折叠或重新展开分支。</Typography.Text>
      <Suspense fallback={graphFallback()}>
        <GraphCanvas
          graph={props.mindMap}
          selectedId={props.selectedTask}
          onSelect={props.onSelect}
          onToggleExpand={(id) => props.mindMap.expandable.has(id) && props.onToggleExpand(id)}
        />
      </Suspense>
    </Space>
  )
}

function DagTab({ props }: { props: Props }) {
  return (
    <Space orientation="vertical" className="full-width">
      <Space>
        <Switch checked={props.showStageOrder} onChange={props.onShowStageOrder} />显示执行顺序边
      </Space>
      <Suspense fallback={graphFallback()}>
        <GraphCanvas graph={props.dag} selectedId={props.selectedTask} onSelect={props.onSelect} />
      </Suspense>
    </Space>
  )
}

export function RunViewTabs(props: Props) {
  const items = [
    { key: 'mindmap', label: '思维导图', children: <MindMapTab props={props} /> },
    { key: 'dag', label: '真实 DAG', children: <DagTab props={props} /> },
    { key: 'list', label: '任务列表', children: <TaskTable tasks={props.tasks} filters={props.filters} onSelect={props.onSelect} /> },
  ]
  return <Card className="view-card"><Tabs activeKey={props.view} onChange={props.onView} items={items} /></Card>
}
