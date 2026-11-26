// Fails when src/api/schema.d.ts is stale relative to ../server/openapi.json.
// Usage: npm run check:api   (regenerate with: npm run gen:api)
import { execSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const spec = process.argv[2] ?? '../server/openapi.json'
const committed = 'src/api/schema.d.ts'
const dir = mkdtempSync(join(tmpdir(), 'api-types-'))
const fresh = join(dir, 'schema.d.ts')
try {
  // one quoted command line through the shell: npx is a .cmd file on Windows, which Node only runs
  // through a shell, and a shell call with an argument list is deprecated (arguments are not escaped)
  execSync(`npx openapi-typescript "${spec}" -o "${fresh}"`, { stdio: 'pipe' })
  if (readFileSync(fresh, 'utf8') !== readFileSync(committed, 'utf8')) {
    console.error(`${committed} is stale relative to ${spec}. Run: npm run gen:api`)
    process.exit(1)
  }
  console.log(`${committed} is up to date with ${spec}`)
} finally {
  rmSync(dir, { recursive: true, force: true })
}
