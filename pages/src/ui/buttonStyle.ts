/**
 * How the site's antd-shaped Button names map onto shadcn's, shared by the
 * Button component and by buttonClass for elements that cannot be a <button>.
 */
import { cn } from './cn'
import { buttonVariants } from './shadcn/button'

export type ButtonVariant = 'primary' | 'default' | 'text' | 'link'
export type ButtonSize = 'small' | 'middle' | 'large'

export const BUTTON_VARIANT = { primary: 'default', default: 'outline', text: 'ghost', link: 'link' } as const
export const BUTTON_SIZE = { small: 'sm', middle: 'default', large: 'lg' } as const
/** shadcn sizes by height and text-sm; this site's three sizes each have their own type size. */
export const BUTTON_TEXT: Record<ButtonSize, string> = {
  small: 'h-7 px-2.5 text-[12.5px]',
  middle: 'px-3.5 text-[13.5px]',
  large: 'px-5 text-[15px]',
}

/**
 * Button's look for an element that cannot be a <button> - the <label> around a
 * hidden file input is the case: the label is what makes the picker open.
 */
export function buttonClass(variant: ButtonVariant = 'default', size: ButtonSize = 'middle', className?: string): string {
  return cn(
    buttonVariants({ variant: BUTTON_VARIANT[variant], size: BUTTON_SIZE[size] }),
    BUTTON_TEXT[size],
    variant === 'primary' && 'font-semibold',
    'cursor-pointer',
    className,
  )
}
