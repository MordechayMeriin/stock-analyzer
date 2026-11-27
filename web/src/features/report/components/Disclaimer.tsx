// Wording from design A2. A client constant, never from the server (spec).
export const DISCLAIMER_TEXT = 'למטרות מידע בלבד. הציונים תיאוריים ואינם המלצה או ייעוץ השקעות.'

export function Disclaimer() {
  return <p className="text-center text-[11px] leading-normal text-[#71717a]">{DISCLAIMER_TEXT}</p>
}
