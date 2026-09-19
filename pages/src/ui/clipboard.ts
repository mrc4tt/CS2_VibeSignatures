import { toast } from 'sonner'

/**
 * Copy text and say whether it worked. The clipboard API is missing outside a
 * secure context and can be refused by the browser; both used to fail
 * silently, so a copy button could do nothing and look like it had worked.
 */
export async function copyText(text: string, messages: { ok: string; failed: string }): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(messages.ok)
    return true
  } catch {
    toast.error(messages.failed)
    return false
  }
}
