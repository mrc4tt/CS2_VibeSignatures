import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChipGroup } from './primitives'

const ITEMS = [
  { value: 'all', label: 'All files', count: 9 },
  { value: 'gap', label: 'Has missing keys', count: 1 },
]

function Harness({ allowEmpty, onChange }: { allowEmpty?: boolean; onChange(next: string | undefined): void }) {
  const [value, setValue] = useState<string | undefined>('all')
  return (
    <ChipGroup
      label="Which files"
      value={value}
      allowEmpty={allowEmpty}
      items={ITEMS}
      onValueChange={(next) => { setValue(next); onChange(next) }}
    />
  )
}

afterEach(cleanup)

describe('ChipGroup', () => {
  it('is one named radiogroup whose chips are radios', () => {
    render(<Harness onChange={() => {}} />)
    const group = screen.getByRole('radiogroup', { name: 'Which files' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /All files/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: /Has missing keys/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('switches on click, and ignores a click on the chosen chip', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.click(screen.getByRole('radio', { name: /Has missing keys/ }))
    expect(onChange).toHaveBeenLastCalledWith('gap')
    await userEvent.click(screen.getByRole('radio', { name: /Has missing keys/ }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('radio', { name: /Has missing keys/ })).toHaveAttribute('aria-checked', 'true')
  })

  it('clears the choice when allowEmpty is set', async () => {
    const onChange = vi.fn()
    render(<Harness allowEmpty onChange={onChange} />)
    await userEvent.click(screen.getByRole('radio', { name: /All files/ }))
    expect(onChange).toHaveBeenLastCalledWith(undefined)
  })
})
