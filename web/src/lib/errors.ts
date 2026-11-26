import { ApiError } from '@/api/client'

/** Hebrew headline per API error code; the server's own message is shown under it. */
export const ERROR_MESSAGES: Record<string, string> = {
  not_cached: 'הנתונים המבוקשים אינם שמורים במטמון המקומי.',
  live_disabled: 'הפעולה דורשת מצב חי.',
  live_required: 'הפעולה זמינה במצב חי בלבד.',
  network_error: 'השרת אינו זמין.',
  selection_too_large: 'הקטע שנבחר גדול מדי.',
  company_already_tracked: 'החברה כבר במעקב.',
  company_not_removable: 'לא ניתן להסיר חברה מרשימת המעקב הקבועה.',
  company_not_found: 'החברה אינה במעקב.',
  validation_error: 'אחד השדות אינו תקין.',
  osint_no_findings: 'המחקר לא מצא ממצאים מאומתים.',
  research_in_progress: 'מחקר לחברה זו ובחלון זה כבר רץ. התוצאה תופיע כשיסתיים.',
}

export function errorCode(error: unknown): string {
  return error instanceof ApiError ? error.code : 'error'
}

export function errorHeadline(error: unknown): string {
  return ERROR_MESSAGES[errorCode(error)] ?? 'הבקשה נכשלה.'
}
