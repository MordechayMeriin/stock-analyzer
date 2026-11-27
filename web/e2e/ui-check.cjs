// Browser checks for tasks 7.2-7.6, tracking companies and the company story page against the running dev server + API.
const { chromium } = require('playwright')
// Needs: API on :8000 (ALLOW_LIVE=false, LLM_FAKE=true) and on :8001 (ALLOW_LIVE=true) with cached
// Malam data and a saved Malam story, and the dev server on :5173. Run: SHOTS=/tmp/shots node e2e/ui-check.cjs
// ONLY=story runs just the story checks, which need only the cached API and the dev server.
// WEB_URL, API_URL and LIVE_API_URL override the default addresses.
const SHOTS = process.env.SHOTS || require('node:os').tmpdir()
const BASE = process.env.WEB_URL || 'http://localhost:5173'
const API = process.env.API_URL || 'http://localhost:8000'
const LIVE_API = process.env.LIVE_API_URL || 'http://localhost:8001'
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
}

/** The company story page: saved story, provenance, citations, live generation (tasks 9.1-9.4). */
async function storyChecks(browser) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

  // 9.1 the saved story on a cached-only server
  await page.goto(BASE + '/MLTM')
  await page.click('[data-testid="story-link"]')
  await page.waitForSelector('[data-testid="story-finding"]')
  check('9.1 company page links to the story page', page.url().endsWith('/MLTM/story'))
  const years = await page.locator('[data-testid="story-years"]').innerText()
  check('9.1 covered years and as_of shown', /FY2023/.test(years) && /FY2025/.test(years) && /\d{4}-\d{2}-\d{2}/.test(years), years)
  for (const id of ['what-it-does', 'what-changed', 'story-vs-numbers']) {
    check(`9.1 section ${id} has content`, (await page.locator(`#${id} ~ *`).count()) > 0)
  }
  const labels = await page.locator('[data-testid="finding-label"]').allInnerTexts()
  check('9.1 findings labelled in words', labels.length > 0 && labels.every((l) => ['עקבי', 'מתח', 'לא מוסבר'].includes(l.trim())), labels.join(','))
  const reason = await page.locator('[data-testid="generate-disabled-reason"]').innerText()
  check('9.4 generate disabled on a cached-only server, with the reason',
    (await page.locator('[data-testid="generate-button"]').isDisabled()) && reason.includes('מטמון בלבד'), reason)
  await page.screenshot({ path: `${SHOTS}/9-story.png`, fullPage: true })

  // 9.2 provenance on keyboard focus, low-confidence mark
  check('9.2 a low-confidence number is marked', (await page.locator('[data-testid="low-confidence"]').count()) > 0)
  const lowButton = page.locator('[data-testid="low-confidence"]').first().locator('xpath=ancestor::button[1]')
  await lowButton.focus()
  const tipId = await lowButton.getAttribute('aria-describedby')
  const tip = page.locator(`[id="${tipId}"]`)
  const tipText = await tip.innerText()
  check('9.2 focus opens the provenance popover with failed checks',
    (await tip.isVisible()) && tipText.includes('ערך מדויק') && /ביטחון נמוך[\s\S]*(CF\d|IS\d|BS\d)/.test(tipText), tipText.replace(/\s+/g, ' ').slice(0, 140))
  await page.screenshot({ path: `${SHOTS}/9-provenance.png` })

  // 9.3 citations: PDF page and reader deep link
  // count() first: a missing link records a FAIL instead of a 30 s timeout that ends the whole run
  const pdfLink = page.locator('[data-testid="citation-pdf-link"]').first()
  const pdf = (await pdfLink.count()) ? await pdfLink.getAttribute('href') : null
  check('9.3 citation links to the PDF page', /#page=\d+$/.test(pdf || ''), pdf)
  const reader = page.locator('[data-testid="citation-reader-link"]').first()
  const href = await reader.getAttribute('href')
  await reader.click()
  await page.waitForURL(`**${href}`)
  await page.waitForSelector('main h1')
  check('9.3 reader link opens the cited year and section', /^\/MLTM\/\d{4}\/report\/.+$/.test(href) && page.url().endsWith(href), href)

  // 9.4 live generation: /health patched to allow live, the POST answered with a canned event stream
  const saved = await (await page.request.get(`${API}/api/companies/MLTM/story`)).json()
  const fresh = { ...saved, run_id: 'e2e0000000000000000000000000000', created_at: new Date().toISOString() }
  const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  const sse = [
    frame('progress', { step: 'reports', message: 'reports selected: FY2023, FY2024, FY2025', data: null }),
    frame('progress', { step: 'agent_start', message: 'describe started', data: null }),
    frame('progress', { step: 'verify', message: 'verifying the story (attempt 1)', data: null }),
    frame('done', fresh),
  ].join('')
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
  await ctx.route('**/health', async (route) => {
    const res = await route.fetch()
    await route.fulfill({ response: res, json: { ...(await res.json()), allow_live: true } })
  })
  let posted = null
  await ctx.route('**/api/companies/MLTM/story', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    posted = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse })
  })
  const p2 = await ctx.newPage()
  await p2.goto(BASE + '/MLTM/story')
  await p2.waitForSelector('[data-testid="story-finding"]')
  const cachedReason = await p2.locator('[data-testid="generate-disabled-reason"]').innerText()
  check('9.4 cached mode on a live-allowed server explains generation needs live mode', cachedReason.includes('מצב חי'), cachedReason)
  await p2.getByRole('radio', { name: 'חי' }).click()
  await p2.click('[data-testid="generate-button"]')
  await p2.waitForFunction(() => document.querySelectorAll('[data-testid="progress-list"] li').length === 3)
  await p2.waitForFunction(() => !document.querySelector('[data-testid="generate-button"]').disabled)
  check('9.4 live generation posts live mode, lists progress, then shows the new story',
    posted?.mode === 'live' && (await p2.locator('[data-testid="story-finding"]').count()) > 0 && (await p2.locator('[role="alert"]').count()) === 0)
  await p2.screenshot({ path: `${SHOTS}/9-live.png` })
  await ctx.close()

  // web evidence (add-story-web-evidence): the saved story with one web source and one press number
  // injected, so the checks do not need a story generated with live search
  const webCtx = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
  // a regex, not a glob: the GET carries ?mode=..., which a glob without a query part does not match
  await webCtx.route(/\/api\/companies\/MLTM\/story(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const res = await route.fetch()
    const run = await res.json()
    const excerpt = 'פורסם 12.10.2026. מלם זכתה במכרז ממשלתי בהיקף 200 מיליון ש"ח לחמש שנים.'
    run.web_sources = {
      'SRC:1': {
        source_id: 'SRC:1', url: 'https://www.globes.co.il/news/e2e-tender', title: 'גלובס: מלם זכתה במכרז',
        excerpts: [excerpt], published_at: '2026-10-12', stored: false, live: true, derived_from_filing: false,
      },
    }
    run.facts = [...run.facts, {
      fact_id: 'WEB:1', kind: 'WEB', name_he: 'מצוטט ממקור רשת: גלובס', unit: 'money', years: [2026],
      value: '200000000', currency: 'ILS', inputs: [], operation: 'quote', source_id: 'SRC:1',
      quote: '200 מיליון', confidence: 'low', failed_checks: ['web_source'],
    }]
    run.rendered.what_changed = [...run.rendered.what_changed, {
      segments: [
        { type: 'text', text: 'לאחר פרסום הדוח זכתה החברה במכרז בהיקף ' },
        { type: 'fact', fact_id: 'WEB:1', display: '200 מיליון ₪' },
        { type: 'caveat', text: 'מקור עיתונאי, לא מבוקר: מצוטט ממקור רשת: גלובס', fact_ids: ['WEB:1'] },
      ],
      paragraph_ids: [],
      source_ids: ['SRC:1'],
    }]
    await route.fulfill({ response: res, json: run })
  })
  const p3 = await webCtx.newPage()
  p3.on('pageerror', (e) => errors.push(String(e)))
  await p3.goto(BASE + '/MLTM/story')
  await p3.waitForSelector('[data-testid="web-citation"]')
  const chip = p3.locator('[data-testid="web-citation"]').first()
  check('web: citation marked as a web source with its title and date',
    (await chip.locator('xpath=ancestor::li[1]').innerText()).includes('מקור רשת') &&
      (await p3.locator('[data-testid="web-citation-date"]').first().innerText()) === '2026-10-12')
  check('web: citation opens the article in a new tab',
    (await chip.getAttribute('target')) === '_blank' && (await chip.getAttribute('rel'))?.includes('noopener') &&
      (await chip.getAttribute('href')) === 'https://www.globes.co.il/news/e2e-tender')
  const press = p3.locator('[data-testid="press-number"]').first().locator('xpath=ancestor::button[1]')
  check('web: press number is marked', (await p3.locator('[data-testid="press-number"]').count()) === 1)
  await press.focus()
  const pressTip = p3.locator(`[id="${await press.getAttribute('aria-describedby')}"]`)
  const pressText = await pressTip.innerText()
  check('web: press number provenance shows source, quote in excerpt and not audited',
    (await pressTip.isVisible()) && pressText.includes('גלובס') && pressText.includes('2026-10-12') &&
      pressText.includes('לא מבוקר') && (await pressTip.locator('mark').innerText()) === '200 מיליון',
    pressText.replace(/\s+/g, ' ').slice(0, 160))
  await p3.screenshot({ path: `${SHOTS}/9-web-evidence.png` })
  await webCtx.close()

  check('story: no console errors', errors.length === 0, errors.slice(0, 3).join(' | '))
  await page.close()
}

async function finish(browser) {
  await browser.close()
  const failed = results.filter((r) => !r.ok)
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
  process.exit(failed.length ? 1 : 0)
}

;(async () => {
  // PW_CHANNEL=msedge (or chrome) uses an installed browser instead of Playwright's own Chromium.
  const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {})
  if (process.env.ONLY === 'story') {
    await storyChecks(browser)
    return finish(browser)
  }
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
  const consoleErrors = []
  page.on('pageerror', (e) => consoleErrors.push(String(e)))
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

  // ---- OSINT stability view (add-osint-web). ONLY=osint runs just this section:
  // OSINT_BASE: a dev server whose API is cached-only and has a stored ELAL result (default BASE).
  // OSINT_LIVE_BASE (optional): a dev server whose API has LLM_FAKE=true and ALLOW_LIVE=true, with ELAL
  // tracked, for the live-run flow. Never point it at a real live API: a run costs OpenRouter credit.
  if (process.env.ONLY === 'osint') {
    const OB = process.env.OSINT_BASE || BASE
    await page.goto(OB + '/ELAL')
    await page.click('[data-testid="osint-link"]')
    await page.waitForSelector('[data-testid="osint-result"]')
    check('osint: company page links to the OSINT view', page.url().endsWith('/ELAL/osint'))
    check('osint: open-sources-only note', (await page.locator('[data-testid="osint-open-sources"]').innerText()).includes('ולא מהדוחות הרשמיים'))
    const areas = await page.locator('[data-testid^="area-"]').count()
    const labelled = await page.locator('[data-testid^="area-"] [data-label]').count()
    // Eight areas since improve-osint-evidence; results stored before it have six (and still load).
    const newAreas = await page.locator('[data-testid="area-legal"], [data-testid="area-regulation"]').count()
    check('osint: six areas (older result) or eight with legal and regulation, each with a label',
      ((areas === 6 && newAreas === 0) || (areas === 8 && newAreas === 2)) && labelled === areas, `${areas} areas, ${labelled} labelled`)
    check('osint: overall label shown', (await page.locator('[data-testid="osint-result"] [data-label]').first().count()) === 1)
    check('osint: risks and strengths listed', (await page.locator('[data-testid="osint-risks"] li').count()) > 0 &&
      (await page.locator('[data-testid="osint-strengths"] li').count()) > 0)
    const sources = page.locator('[data-testid="source"]')
    const n = await sources.count()
    // One primary link per source; merged duplicates add theirs under "also reported in" (also-sources).
    const primaryLinks = await sources.evaluateAll((els) =>
      els.map((e) => [...e.querySelectorAll('a[target="_blank"]')].filter((a) => !a.closest('[data-testid="also-sources"]')).length))
    check('osint: numbered sources, each with one primary link', n > 0 && primaryLinks.every((k) => k === 1),
      `${n} sources, ${await page.locator('[data-testid="also-sources"]').count()} with merged duplicates`)
    const filing = await page.locator('[data-testid="source"][data-filing="true"]').count()
    const filingMarks = await page.locator('[data-testid="filing-mark"]').count()
    const undated = await page.locator('[data-testid="source"][data-undated="true"]').count()
    const undatedMarks = await page.locator('[data-testid="undated-mark"]').count()
    check('osint: every filing-derived source is marked, and only those', filing === filingMarks, `${filing}/${filingMarks}`)
    check('osint: every undated source is marked, and only those', undated === undatedMarks, `${undated}/${undatedMarks}`)
    const cite = page.locator('[data-testid="osint-risks"] a[href^="#source-"]').first()
    const target = (await cite.getAttribute('href')).slice(1)
    await cite.click()
    const top = await page.locator(`#${target}`).evaluate((e) => e.getBoundingClientRect().top)
    const header = await page.locator('header').evaluate((e) => e.getBoundingClientRect().bottom)
    check('osint: a cited finding number scrolls to its source, below the sticky header', top >= header, `${top} vs ${header}`)
    check('osint: cached mode offers no run and says live mode is needed',
      (await page.locator('[data-testid="osint-run-button"]').count()) === 0 &&
      (await page.locator('[data-testid="osint-live-needed"]').count()) === 1)
    await page.screenshot({ path: `${SHOTS}/o1-osint.png`, fullPage: true })
    await page.selectOption('[data-testid="osint-window"]', '12')
    await page.waitForFunction(() => {
      const meta = document.querySelector('[data-testid="osint-meta"]')
      return (meta && meta.textContent.includes('(12 ')) || document.body.textContent.includes('בחלון של 12 חודשים')
    })
    check('osint: another window shows its own result or says none was run', true)
    await page.selectOption('[data-testid="osint-window"]', '36')

    if (process.env.OSINT_LIVE_BASE) {
      const LB = process.env.OSINT_LIVE_BASE
      await page.goto(LB + '/ELAL/osint')
      await page.evaluate(() => localStorage.setItem('analyzer.mode', 'live'))
      await page.reload()
      let posts = 0
      page.on('request', (r) => r.method() === 'POST' && r.url().includes('/osint') && posts++)
      await page.click('[data-testid="osint-run-button"]')
      const warning = await page.locator('[data-testid="osint-confirm"]').innerText()
      check('osint live: cost warning before a run', warning.includes('$1') && warning.includes('OpenRouter'))
      await page.click('[data-testid="osint-cancel"]')
      check('osint live: cancelling the warning starts no run', posts === 0 &&
        (await page.locator('[data-testid="osint-run-button"]').count()) === 1)
      await page.click('[data-testid="osint-run-button"]')
      await page.click('[data-testid="osint-confirm-run"]')
      const fresh = await page
        .waitForFunction(() => {
          const meta = document.querySelector('[data-testid="osint-meta"]')
          return !document.querySelector('[data-testid="osint-progress"]') && meta && !meta.textContent.includes('תוצאה שמורה')
        }, null, { timeout: 30000 })
        .then(() => true, () => false)
      check('osint live: confirmed run shows the new result', fresh && posts === 1, `posts ${posts}`)
      await page.reload()
      await page.waitForSelector('[data-testid="osint-meta"]')
      check('osint live: the new result is stored', (await page.locator('[data-testid="osint-meta"]').innerText()).includes('תוצאה שמורה'))
      await page.screenshot({ path: `${SHOTS}/o2-osint-live.png`, fullPage: true })
    }

    const errors = consoleErrors.filter((e) => !e.includes('status of 409'))
    check('osint: no console errors', errors.length === 0, errors.slice(0, 3).join(' | '))
    const failed = results.filter((r) => !r.ok)
    console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
    await browser.close()
    process.exit(failed.length ? 1 : 0)
  }

  // ---- ratios view (add-financial-ratios 7.3). Needs cached financials for MLTM and LUMI on :8000.
  // ONLY=ratios runs just this section.
  const tickX = async (card, label) =>
    (await card.locator('.recharts-xAxis-tick-labels text', { hasText: label }).first().boundingBox()).x
  const fys = async (card) => card.locator('circle[data-testid="point"]').evaluateAll((els) => els.map((e) => Number(e.dataset.fy)))
  const hoverYear = async (card, label) => {
    await card.scrollIntoViewIfNeeded()
    const box = await card.locator('[data-testid="ratio-chart"]').boundingBox()
    const t = await card.locator('.recharts-xAxis-tick-labels text', { hasText: label }).first().boundingBox()
    await page.mouse.move(t.x + t.width / 2, box.y + box.height / 2)  // labels are centered on their year
    return card.locator('[data-testid="ratio-tooltip"]')
  }
  await page.goto(BASE + '/MLTM')
  await page.click('[data-testid="ratios-link"]')
  await page.waitForSelector('[data-testid="ratio-gross_margin"] circle[data-testid="point"]')
  const gross = page.locator('[data-testid="ratio-gross_margin"]')
  check('ratios: Malam gross margin shows 10.47% for FY2025', (await gross.locator('[data-testid="latest-value"]').innerText()).includes('10.47%'))
  check('ratios: years increase left to right in the RTL page', (await tickX(gross, '2021')) < (await tickX(gross, '2025')))
  check('ratios: gross margin has a point for every year', JSON.stringify((await fys(gross)).sort()) === '[2021,2022,2023,2024,2025]')
  const change = gross.locator('[data-testid="change"]')
  check('ratios: latest value shows its change and status (stable)', (await change.getAttribute('data-status')) === 'stable' && (await change.innerText()).includes('0.13'), await change.innerText())
  const quick = page.locator('[data-testid="ratio-quick_ratio"]')
  check('ratios: missing years have no point (quick ratio FY2021-22)', JSON.stringify((await fys(quick)).sort()) === '[2023,2024,2025]', JSON.stringify(await fys(quick)))
  const qTip = await hoverYear(quick, '2021')
  check('ratios: hovering a missing year shows the reason', (await qTip.locator('[data-testid="missing-reason"]').innerText()).includes('חסר נתון'))
  const roe = page.locator('[data-testid="ratio-roe"]')
  check('ratios: low-confidence point is marked', (await roe.locator('circle[data-fy="2025"][data-low="true"]').count()) === 1)
  const rTip = await hoverYear(roe, '2025')
  check('ratios: low-confidence details name the failed check', (await rTip.locator('[data-testid="low-confidence-details"]').innerText()).includes('BS5'))
  await page.screenshot({ path: `${SHOTS}/r1-malam-ratios.png`, fullPage: true })
  await page.fill('[data-testid="as-of"]', '2026-03-01')
  await page.waitForFunction(() => !document.querySelector('[data-testid="ratio-gross_margin"] circle[data-fy="2025"]'))
  check('ratios: availability date before FY2025 removes the FY2025 point', !(await fys(gross)).includes(2025))
  await page.click('[data-testid="table-toggle"]')
  check('ratios: table view lists every ratio row', (await page.locator('tr[data-code="gross_margin"]').count()) === 1)
  await page.goto(BASE + '/LUMI/ratios')
  await page.waitForSelector('[data-testid="group-credit"]')
  check('ratios: bank shows credit and capital groups and no margin charts',
    (await page.locator('[data-testid="group-capital"]').count()) === 1 && (await page.locator('[data-testid="ratio-gross_margin"]').count()) === 0)
  check('ratios: a ratio with no value in any year shows a no-data message, not empty axes',
    (await page.locator('[data-testid="ratio-roa"] [data-testid="no-data"]').count()) === 1 &&
    (await page.locator('[data-testid="ratio-roa"] [data-testid="ratio-chart"]').count()) === 0)
  await page.screenshot({ path: `${SHOTS}/r2-leumi-ratios.png`, fullPage: true })
  if (process.env.ONLY === 'ratios') {
    const failed = results.filter((r) => !r.ok)
    const errors = consoleErrors.filter((e) => !e.includes('status of 409'))
    check('ratios: no console errors', errors.length === 0, errors.slice(0, 3).join(' | '))
    console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
    await browser.close()
    process.exit(results.some((r) => !r.ok) ? 1 : 0)
  }

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

  // ---- tracking companies: add/remove need live mode (search answer mocked: no cached provider data needed)
  const untrackedHit = [{ fr_company_id: 1234, name: 'Example Holdings Ltd.', ticker: 'EXMP', isin: null, country_code: 'IL', tracked_ticker: null }]
  await page.route('**/api/companies/search?*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(untrackedHit) }))
  await page.getByRole('textbox', { name: 'חיפוש חברה' }).fill('דוגמה')
  await page.getByRole('button', { name: 'חיפוש' }).click()
  await page.waitForSelector('[data-testid="hit-1234"]')
  const addBtn = page.locator('[data-testid="hit-1234"]').getByRole('button', { name: 'הוסף למעקב' })
  const gateNote = await page.locator('[data-testid="tracking-gate"]').innerText()
  check('tracking: add action disabled on a cached-only server, with the server reason',
    (await addBtn.isDisabled()) && gateNote.includes('ALLOW_LIVE=false'), gateNote)
  check('tracking: no remove action on the version-controlled MLTM', (await page.locator('[data-testid="remove-MLTM"]').count()) === 0)
  await page.unroute('**/api/companies/search?*')

  // same app pointed at the live-allowed server via runtime /config.js
  const ctx2 = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
  await ctx2.route('**/config.js', (r) => r.fulfill({ contentType: 'application/javascript', body: `window.__APP_CONFIG__ = { apiBaseUrl: '${LIVE_API}' }` }))
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
  check('7.3 filings shown without links to their PDFs', (await page.locator('a[href*=".pdf"]').count()) === 0)
  await page.screenshot({ path: `${SHOTS}/2-company.png`, fullPage: true })

  // ---- reports the provider has not processed (use-filing-processing-status), routed responses
  const rmliCompany = { ticker: 'RMLI', name_he: 'רמי לוי', name_en: null, fr_company_id: 7010, isin: null, source: 'added' }
  const pdf = (id, fy, status, size) => ({
    filing_id: id, title: `דוח תקופתי ושנתי לשנת ${fy}`, fiscal_year: fy, release_datetime: `${fy + 1}-03-27T13:07:01Z`,
    file_extension: 'PDF', file_size: size, selected: true, cached: false, processing_status: status,
  })
  const yearOf = (fy, availability, status, cached = false) => {
    const f = { ...pdf(60000000 + fy, fy, status, 14456209), cached }
    return { fiscal_year: fy, selected_filing_id: f.filing_id, selection_error: null, report_cached: cached, markdown_availability: availability, filings: [f] }
  }
  const rmliFilings = {
    ticker: 'RMLI',
    years: [
      yearOf(2025, 'available', 'COMPLETED'),
      yearOf(2024, 'processing', 'QUEUED'),
      yearOf(2023, 'processing', 'QUEUED', true),
      yearOf(2022, 'failed', 'FAILED'),
      yearOf(2021, 'unknown', null),
    ],
  }
  await page.route('**/api/companies/RMLI/filings?*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(rmliFilings) }))
  await page.route('**/api/companies/RMLI?*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(rmliCompany) }))
  await page.goto(BASE + '/RMLI')
  await page.waitForSelector('[data-testid="year-2024"]')
  const yr = (fy) => page.locator(`[data-testid="year-${fy}"]`)
  const readLinks = (fy) => yr(fy).getByRole('link', { name: /קריאת הדוח|שאלה ל-LLM/ }).count()
  check('processing: a year the provider has not processed is marked, explained, and offers no read/ask',
    (await yr(2024).locator('[data-testid="not-processed-badge"]').count()) === 1 &&
      (await yr(2024).locator('[data-testid="unavailable-reason"]').innerText()).includes('טרם המיר') &&
      (await readLinks(2024)) === 0)
  check('processing: a year the provider could not convert is marked and offers no read/ask',
    (await yr(2022).locator('[data-testid="conversion-failed-badge"]').count()) === 1 && (await readLinks(2022)) === 0)
  check('processing: a cached report stays readable whatever its availability',
    (await yr(2023).locator('[data-testid="not-processed-badge"]').count()) === 0 && (await readLinks(2023)) === 2)
  check('processing: available and unknown years keep their read/ask actions',
    (await readLinks(2025)) === 2 && (await readLinks(2021)) === 2 &&
      (await page.locator('[data-testid="unavailable-reason"]').count()) === 2)
  await page.screenshot({ path: `${SHOTS}/2b-not-processed.png`, fullPage: true })
  await page.unroute('**/api/companies/RMLI/filings?*')
  await page.unroute('**/api/companies/RMLI?*')

  // ---- 7.4 reader via deep link to the risk section
  await page.goto(BASE + '/MLTM/2025/report/business-22')
  await page.waitForSelector('[data-testid="node-title"]')
  const title = await page.locator('[data-testid="node-title"]').innerText()
  check('7.4 deep link opens the risk section', title.includes('דיון בגורמי סיכון') && title.includes('22'), title)
  check('7.4 tree highlights the active node', (await page.locator('[aria-current="true"][data-node-id="business-22"]').count()) === 1)
  const markers = (await page.locator('[data-testid="page-marker"]').allInnerTexts()).map((t) => t.trim())
  check('7.4 page markers show the printed page (else the page in the file)',
    markers.length > 0 && markers.every((m) => /עמ' \d+|עמוד \d+ בקובץ/.test(m)), `${markers.length} markers; first: ${markers[0]}`)
  check("7.4 first risk page shows printed page 57", markers[0]?.includes("עמ' 57"), markers[0])
  check('7.4 no page marker or link opens the source PDF',
    (await page.locator('[data-testid="page-marker"] a').count()) === 0 && (await page.locator('a[href*=".pdf"]').count()) === 0)
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
  const sources = await page.locator('[data-testid="source-ids"] li').allInnerTexts()
  const readerLink = page.locator('[data-testid="answer-meta"] a[href$="/MLTM/2025/report/business-22.1"]')
  check('7.6 answer streamed and completed', (await page.locator('[data-testid="answer"]').innerText()).includes('תשובה לדוגמה'))
  check('7.6 cost and supplied paragraph ids shown when done',
    meta.includes('$0.00') && sources.length > 0 && sources.every((t) => /^MLTM-2025-p\d{4}-\d{3}$/.test(t.trim())), `${sources.length} paragraph ids`)
  check('7.6 link to the section in the reader, none to the PDF',
    (await readerLink.count()) === 1 && (await page.locator('[data-testid="answer-meta"] a[href*=".pdf"]').count()) === 0)
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
  await storyChecks(browser)
  await finish(browser)
})().catch((e) => {
  console.error(e)
  process.exit(2)
})
