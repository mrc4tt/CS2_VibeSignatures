import { describe, expect, it } from 'vitest'
import { makeSnapshot, makeTask } from '../test/fixtures'
import { buildDag, buildMindMap, defaultMindMapExpansion } from './model'

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

  it('expands all skill descendants by default', () => {
    const snapshot = makeSnapshot()
    const graph = snapshot.graph!
    const root = graph.nodes[0]
    const childId = `${root.job_id}/child`
    const grandchildId = `${root.job_id}/grandchild`
    graph.nodes.push(
      { ...root, id: childId, name: 'child', order: 1, layer: 1 },
      { ...root, id: grandchildId, name: 'grandchild', order: 2, layer: 2 },
    )
    graph.edges.push(
      { source: root.id, target: childId, edge_type: 'artifact', artifact: null },
      { source: childId, target: grandchildId, edge_type: 'artifact', artifact: null },
    )
    const tasks = [
      ...snapshot.tasks,
      makeTask({ task_id: childId, name: 'child' }),
      makeTask({ task_id: grandchildId, name: 'grandchild' }),
    ]

    const expanded = defaultMindMapExpansion(graph)
    const result = buildMindMap(snapshot.run, graph, tasks, { query: '' }, expanded)

    expect(expanded).toEqual(new Set([root.id, childId]))
    expect(result.nodes.map((node) => node.id)).toContain(childId)
    expect(result.nodes.map((node) => node.id)).toContain(grandchildId)
    expect(result.parentById[childId]).toBe(root.id)
    expect(result.parentById[grandchildId]).toBe(childId)
  })

  it('excludes stage order unless explicitly enabled in DAG mode', () => {
    const snapshot = makeSnapshot()
    const graph = snapshot.graph!
    graph.edges.push({ source: graph.nodes[0].id, target: graph.nodes[0].id, edge_type: 'stage_order', artifact: null })
    expect(buildDag(graph, snapshot.tasks, { query: '', jobId: 'all' }, false).edges).toHaveLength(0)
    expect(buildDag(graph, snapshot.tasks, { query: '', jobId: 'all' }, true).edges).toHaveLength(1)
  })
})
