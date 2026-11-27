import { Moon, Sun } from 'lucide-react'

import { setTheme, useTheme } from '@/app/theme'

/** One button: switches to the other theme. The first click turns "follow the device" into a choice. */
export function ThemeToggle() {
  const { dark } = useTheme()
  const label = dark ? 'מעבר למצב בהיר' : 'מעבר למצב כהה'
  return (
    <button
      type="button"
      onClick={() => setTheme(dark ? 'light' : 'dark')}
      aria-label={label}
      title={label}
      className="grid size-11 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {dark ? <Sun className="size-[18px]" aria-hidden /> : <Moon className="size-[18px]" aria-hidden />}
    </button>
  )
}
