import { describe, expect, it } from 'vitest'
import { makeSnapshot, makeTask } from '../test/fixtures'
import { buildDag, buildMindMap } from './model'

describe('graph projections', () => {
  it('selects the deepest same-job dependency and preserves other edges', () => {
    const snapshot = makeSnapshot()
    const graph = snapshot.graph!
    const base = graph.nodes[0]
    graph.nodes.push(
      { ...base, id: `${base.job_id}/parent-a`, name: 'parent-a', order: 1, layer: 1 },
      { ...base, id: `${base.job_id}/parent-b`, name: 'parent-b', order: 2, layer: 2 },
      { ...base, id: `${base.job_id}/child`, name: 'child', order: 3, layer: 3 },
    )
    graph.edges.push(
      { source: `${base.job_id}/parent-a`, target: `${base.job_id}/child`, edge_type: 'artifact', artifact: null },
      { source: `${base.job_id}/parent-b`, target: `${base.job_id}/child`, edge_type: 'prerequisite', artifact: null },
    )
    const tasks = [...snapshot.tasks, makeTask({ task_id: `${base.job_id}/parent-a`, name: 'parent-a' }), makeTask({ task_id: `${base.job_id}/parent-b`, name: 'parent-b' }), makeTask({ task_id: `${base.job_id}/child`, name: 'child' })]
    const result = buildMindMap(snapshot.run, graph, tasks, { query: '' }, new Set([`${base.job_id}/parent-b`]))
    expect(result.parentById[`${base.job_id}/child`]).toBe(`${base.job_id}/parent-b`)
    expect(result.edges.some((edge) => edge.secondary && edge.source.endsWith('parent-a'))).toBe(true)
  })

  it('excludes stage order unless explicitly enabled in DAG mode', () => {
    const snapshot = makeSnapshot()
    const graph = snapshot.graph!
    graph.edges.push({ source: graph.nodes[0].id, target: graph.nodes[0].id, edge_type: 'stage_order', artifact: null })
    expect(buildDag(graph, snapshot.tasks, { query: '', jobId: 'all' }, false).edges).toHaveLength(0)
    expect(buildDag(graph, snapshot.tasks, { query: '', jobId: 'all' }, true).edges).toHaveLength(1)
  })
})
