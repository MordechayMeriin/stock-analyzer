// Browser checks for tasks 7.2-7.6 against the running dev server + API.
const { chromium } = require('playwright')
// Needs: API on :8000 (ALLOW_LIVE=false, LLM_FAKE=true) and on :8001 (ALLOW_LIVE=true) with cached
// Malam data, and the dev server on :5173. Run: SHOTS=/tmp/shots node e2e/ui-check.cjs
const SHOTS = process.env.SHOTS || require('node:os').tmpdir()
const BASE = 'http://localhost:5173'
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
}

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
  const consoleErrors = []
  page.on('pageerror', (e) => consoleErrors.push(String(e)))
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

  // ---- 7.2 shell: RTL + mode control reflects /health (cached-only server)
  await page.goto(BASE + '/')
  await page.waitForSelector('[data-testid="company-MLTM"]')
  const dir = await page.evaluate(() => getComputedStyle(document.documentElement).direction)
  check('7.2 html renders RTL', dir === 'rtl', dir)
  const navBox = await page.locator('nav[aria-label="ניווט ראשי"]').boundingBox()
  const brandBox = await page.locator('header a', { hasText: 'הוועדה' }).boundingBox()
  check('7.2 brand sits on the right of the nav (RTL layout)', brandBox.x > navBox.x, `brand x=${brandBox.x} nav x=${navBox.x}`)
  const mc = page.locator('[data-testid="mode-control"]')
  check('7.2 mode control locked to cached when server disallows live',
    (await mc.getAttribute('data-mode')) === 'cached' && (await mc.getAttribute('data-locked')) === 'true' &&
      (await page.getByRole('radio', { name: 'חי' }).isDisabled()))
  check('7.2 lock explanation shown', await page.getByText('השרת מוגדר למצב מטמון בלבד').first().isVisible())
  await page.screenshot({ path: `${SHOTS}/1-home.png` })

  // same app pointed at the live-allowed server via runtime /config.js
  const ctx2 = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
  await ctx2.route('**/config.js', (r) => r.fulfill({ contentType: 'application/javascript', body: "window.__APP_CONFIG__ = { apiBaseUrl: 'http://localhost:8001' }" }))
  const p2 = await ctx2.newPage()
  await p2.goto(BASE + '/')
  await p2.waitForSelector('[data-testid="company-MLTM"]')
  const mc2 = p2.locator('[data-testid="mode-control"]')
  const liveEnabled = !(await p2.getByRole('radio', { name: 'חי' }).isDisabled())
  await p2.getByRole('radio', { name: 'חי' }).click()
  check('7.2 mode control unlocked on a live-allowed server and switches to live',
    liveEnabled && (await mc2.getAttribute('data-mode')) === 'live' && (await mc2.getAttribute('data-locked')) === 'false')
  await ctx2.close()

  // ---- 7.3 company and filing browser
  await page.click('[data-testid="company-MLTM"]')
  await page.waitForSelector('[data-testid="year-2025"]')
  const y25 = page.locator('[data-testid="year-2025"]')
  const y24 = page.locator('[data-testid="year-2024"]')
  const sel25 = await y25.locator('[data-selected="true"]').innerText()
  const sel24 = await y24.locator('[data-selected="true"]').innerText()
  check('7.3 FY2025 selected report is 32935334 and cached', sel25.includes('#32935334') && (await y25.locator('[data-testid="cached-badge"]').count()) === 1, sel25.replace(/\s+/g, ' ').slice(0, 90))
  check('7.3 FY2024 selected report is 63741657 and cached', sel24.includes('#63741657') && (await y24.locator('[data-testid="cached-badge"]').count()) === 1, sel24.replace(/\s+/g, ' ').slice(0, 90))
  check('7.3 HTM cover / iXBRL filings listed but not selected',
    (await y25.getByText('#32935333').count()) === 1 && (await y24.getByText('#63741654').count()) === 1)
  const usageText = await page.locator('[data-testid="usage-panel"]').innerText()
  check('7.3 credit usage visible', /קרדיטים/.test(usageText) && /\d+ \/ 500/.test(usageText), usageText.replace(/\s+/g, ' ').slice(0, 120))
  check('7.3 company context in header', (await page.locator('[data-testid="company-context"]').innerText()).includes('מלם תים'))
  await page.screenshot({ path: `${SHOTS}/2-company.png`, fullPage: true })

  // ---- 7.4 reader via deep link to the risk section
  await page.goto(BASE + '/MLTM/2025/report/business-22')
  await page.waitForSelector('[data-testid="node-title"]')
  const title = await page.locator('[data-testid="node-title"]').innerText()
  check('7.4 deep link opens the risk section', title.includes('דיון בגורמי סיכון') && title.includes('22'), title)
  check('7.4 tree highlights the active node', (await page.locator('[aria-current="true"][data-node-id="business-22"]').count()) === 1)
  const links = await page.locator('[data-testid="page-link"]').evaluateAll((as) => as.map((a) => ({ href: a.href, text: a.textContent })))
  const pdfOk = links.length > 0 && links.every((l) => /\.pdf#page=\d+$/.test(l.href))
  const firstLink = links[0]
  check('7.4 page links target the PDF with #page=N', pdfOk, `${links.length} links; first: ${firstLink?.text?.trim()} → ${firstLink?.href.split('/').pop()}`)
  check('7.4 first risk page is PDF page 58 (printed 57)', firstLink?.href.endsWith('#page=58') && firstLink.text.includes("57"))
  // mixed Hebrew/Latin: find the AI risk paragraph and check the "(AI)" run keeps Latin order
  const ai = page.locator('[data-pid]', { hasText: 'בינה מלאכותית (AI)' }).first()
  await ai.scrollIntoViewIfNeeded()
  const aiText = await ai.innerText()
  const aiDir = await ai.evaluate((el) => getComputedStyle(el).direction)
  check('7.4 mixed Hebrew/Latin paragraph renders RTL with "(AI)" intact', aiDir === 'rtl' && aiText.includes('(AI)'), aiText.slice(0, 80))
  const pct = page.locator('[data-pid]', { hasText: '34.8%' }).first()
  check('7.4 percentage "34.8%" kept as one run', (await pct.count()) === 1 && (await pct.innerText()).includes('34.8%'))
  await ai.screenshot({ path: `${SHOTS}/3b-mixed-text.png` })
  await page.screenshot({ path: `${SHOTS}/3-reader.png` })
  // navigation through the tree
  await page.locator('[data-node-id="business-19"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="node-title"]')?.textContent?.includes('הליכים משפטיים'))
  check('7.4 tree click navigates and updates URL', page.url().endsWith('/MLTM/2025/report/business-19'))

  // ---- 7.5 financials
  await page.goto(BASE + '/MLTM/financials')
  await page.waitForSelector('[data-testid="statement-income"]')
  const currency = await page.locator('[data-testid="currency-label"]').innerText()
  const headers = await page.locator('[data-testid="statement-income"] thead th').allInnerTexts()
  const revenueRow = await page.locator('[data-testid="statement-income"] tr[data-code="revenue"]').innerText()
  check('7.5 currency label shown', currency.includes('ILS') && currency.includes('₪'), currency.replace(/\s+/g, ' '))
  check('7.5 one column per fiscal year', headers.slice(1).map((h) => h.split('\n')[0]).join(',') === 'FY2025,FY2024,FY2023,FY2022,FY2021', headers.map((h) => h.split('\n')[0]).join(','))
  check('7.5 FY2025 revenue exact in currency', revenueRow.includes('4,138,004,000 ₪'), revenueRow.replace(/\s+/g, ' ').slice(0, 120))
  check('7.5 income, balance sheet and cash flow grouped',
    (await page.locator('[data-testid="statement-balance_sheet"]').count()) === 1 && (await page.locator('[data-testid="statement-cash_flow"]').count()) === 1)
  await page.screenshot({ path: `${SHOTS}/4-financials.png` })

  // ---- 7.6 playground against the FakeLLM-backed server
  await page.goto(BASE + '/MLTM/2025/playground?node=business-22.1')
  await page.waitForSelector('select[aria-label="סעיף"]')
  check('7.6 node preselected from the reader link', (await page.locator('select[aria-label="סעיף"]').inputValue()) === 'business-22.1')
  await page.fill('textarea', 'מהם גורמי הסיכון החיצוניים?')
  await page.click('button[type="submit"]')
  await page.waitForSelector('[data-testid="answer"][data-status="done"]', { timeout: 15000 })
  const meta = await page.locator('[data-testid="answer-meta"]').innerText()
  const sources = await page.locator('[data-testid="source-links"] a').evaluateAll((as) => as.map((a) => a.href))
  check('7.6 answer streamed and completed', (await page.locator('[data-testid="answer"]').innerText()).includes('תשובה לדוגמה'))
  check('7.6 cost and source-paragraph links shown when done', meta.includes('$0.00') && sources.length > 0 && sources.every((h) => /#page=\d+$/.test(h)), `${sources.length} sources`)
  await page.screenshot({ path: `${SHOTS}/5-playground.png` })

  // cancel: a stream that sends one delta and stays open until the client aborts
  await page.evaluate(() => {
    const realFetch = window.fetch
    window.fetch = (input, init) => {
      if (String(input).includes('/api/playground')) {
        const enc = new TextEncoder()
        const body = new ReadableStream({
          start(controller) {
            controller.enqueue(enc.encode('event: delta\r\ndata: {"text": "תשובה חלקית שתיעצר באמצע "}\r\n\r\n'))
            init.signal.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')))
          },
        })
        return Promise.resolve(new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }))
      }
      return realFetch(input, init)
    }
  })
  await page.fill('textarea', 'שאלה שתבוטל')
  await page.click('button[type="submit"]')
  await page.waitForSelector('[data-testid="answer"][data-status="streaming"]')
  await page.getByRole('button', { name: 'עצירה' }).click()
  await page.waitForSelector('[data-testid="answer"][data-status="cancelled"]', { timeout: 5000 })
  const ans = page.locator('[data-testid="answer"]')
  const ansText = await ans.innerText()
  check('7.6 cancel stops the stream and keeps the partial answer, marked cancelled',
    ansText.includes('תשובה חלקית שתיעצר באמצע') && ansText.includes('בוטלה'), ansText.replace(/\s+/g, ' ').slice(0, 80))
  await page.screenshot({ path: `${SHOTS}/6-cancel.png` })

  // ---- shared states: not-cached error with retry (FY2024 report is cached locally? test a year that is not)
  await page.goto(BASE + '/MLTM/2023/report')
  await page.waitForSelector('[role="alert"]')
  const alert = await page.locator('[role="alert"]').innerText()
  check('states: not-cached view explains and offers retry (live locked)', alert.includes('אינם שמורים') && alert.includes('נסה שוב') && alert.includes('מטמון בלבד'))

  const unexpected = consoleErrors.filter((e) => !e.includes('status of 409'))
  check('no unexpected console errors (the 409 is the deliberate not-cached check)', unexpected.length === 0, unexpected.slice(0, 3).join(' | '))
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
  process.exit(failed.length ? 1 : 0)
})().catch((e) => {
  console.error(e)
  process.exit(2)
})
