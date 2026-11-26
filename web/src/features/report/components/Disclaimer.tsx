export const DISCLAIMER_TEXT = 'המידע מוצג למטרות מידע בלבד ואינו מהווה המלצה או ייעוץ השקעות.'

export function Disclaimer() {
  return <p className="text-xs text-muted-foreground">{DISCLAIMER_TEXT}</p>
}
