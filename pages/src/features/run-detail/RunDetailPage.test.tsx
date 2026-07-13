import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeSnapshot } from '../../test/fixtures'
import { useRunLiveStore } from './liveStore'
import { RunDetailPage } from './RunDetailPage'

vi.mock('./useRunLive', () => ({
  useRunLive: () => ({
    snapshotQuery: { isLoading: false, error: null, refetch: vi.fn() },
    runQuery: {},
  }),
}))

describe('RunDetailPage', () => {
  beforeEach(() => {
    const snapshot = makeSnapshot()
    snapshot.graph = null
    useRunLiveStore.getState().replaceSnapshot(snapshot)
  })

  it('keeps queued runs visible while the graph is not initialized', () => {
    render(
      <MemoryRouter initialEntries={['/runs/run-1']}>
        <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText(/等待 ExecutionPlan 初始化/)).toBeInTheDocument()
  })
})
