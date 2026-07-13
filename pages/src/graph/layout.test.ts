import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout'
import type { VisualGraph } from './model'

describe('ELK layout', () => {
  it('lays out a 500-node graph', async () => {
    const graph: VisualGraph = {
      nodes: Array.from({ length: 500 }, (_, index) => ({
        id: `node-${index}`,
        label: `Node ${index}`,
        subtitle: 'skill',
        kind: 'skill',
        status: 'pending',
        descendantCount: 0,
      })),
      edges: Array.from({ length: 499 }, (_, index) => ({
        id: `edge-${index}`,
        source: `node-${index}`,
        target: `node-${index + 1}`,
        edgeType: 'artifact',
        secondary: false,
        layout: true,
      })),
      parentById: {},
      expandable: new Set(),
    }
    const positions = await layoutGraph(graph)
    expect(Object.keys(positions)).toHaveLength(500)
  }, 15_000)
})
