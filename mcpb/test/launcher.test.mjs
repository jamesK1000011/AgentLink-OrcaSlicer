// SPDX-License-Identifier: LGPL-2.1-or-later
// The extension's launcher as Claude starts it: it finds a Python, serves
// this checkout (ORCALINK_FROM), and answers initialize, tools/list and a
// call. Then with no Python at all: it still answers, and says why.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..', '..')
const launcher = path.join(root, 'mcpb', 'server', 'index.js')
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'orcalink-launcher-'))

function run(env, which = launcher, linger = 0) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [which], { env: { ...process.env, HOME: tmp, ORCALINK_LOG_DIR: path.join(tmp, 'logs'), AGENTLINK_OUT: path.join(tmp, 'out'), ...env }, stdio: ['pipe', 'pipe', 'pipe'] })
    const got = new Map()
    let buf = ''
    child.stdout.on('data', (d) => {
      buf += d
      let i
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i)
        buf = buf.slice(i + 1)
        const m = JSON.parse(line) // only protocol lines reach stdout
        got.set(m.id, m)
        if (got.size === 3) {
          // Claude keeps the extension running: linger gives the background
          // update its time before this one is stopped.
          setTimeout(() => child.kill(), linger)
          resolve(got)
        }
      }
    })
    setTimeout(() => {
      child.kill()
      reject(new Error('no answer: ' + fs.readFileSync(path.join(tmp, 'logs', 'launcher.log'), 'utf8').slice(-2000)))
    }, 60000)
    const send = (m) => child.stdin.write(JSON.stringify(m) + '\n')
    send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '0' } } })
    send({ jsonrpc: '2.0', method: 'notifications/initialized' })
    send({ jsonrpc: '2.0', id: 2, method: 'tools/list' })
    send({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'orca_status', arguments: {} } })
  })
}

function check(ok, what) {
  if (!ok) {
    console.error('FAIL:', what)
    process.exit(1)
  }
}

const a = await run({ ORCALINK_FROM: root, ORCALINK_PYTHON: process.env.PYTHON || 'python3' })
check(a.get(1).result.serverInfo.name === 'orcaslicer-agentlink', 'initialize names the server')
const names = a.get(2).result.tools.map((t) => t.name)
check(['orca_project', 'orca_paint', 'orca_slice', 'gcode_read', 'orca_calibrate', 'orca_status'].every((n) => names.includes(n)), 'the tools are listed')
check(JSON.parse(a.get(3).result.content[0].text).out === path.join(tmp, 'out'), 'orca_status answers with the output folder')

// No Python anywhere it looks: an answer that says so, never silence.
const b = await run({ ORCALINK_FROM: root, ORCALINK_PYTHON: '/nonexistent/python3', PATH: '/nonexistent' })
check(/Python 3\.9/.test(b.get(1).result.instructions) && b.get(3).result.isError, 'without a Python it says what it needs')
// The update path, against a stand-in GitHub serving this checkout as commit
// aaa…: the first start serves the bundled copy and fetches it in the
// background; the next start serves it. A commit that does not load (bbb…)
// is kept out and the good one goes on serving.
import http from 'node:http'
const files = fs.readFileSync(path.join(root, 'FILES'), 'utf8').split('\n').filter(Boolean)
let head = 'a'.repeat(40)
const srv = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0])
  if (u.endsWith('/info/refs')) return res.end(`001e# service=git-upload-pack\n0000${'0'.repeat(4)}${head} refs/heads/main\n`)
  const m = u.match(/^\/[^/]+\/[^/]+\/([0-9a-f]{40})\/(.+)$/)
  if (!m) return res.writeHead(404).end()
  const [, sha, f] = m
  if (f === 'FILES') return res.end(files.join('\n') + '\n')
  if (sha.startsWith('b') && f === 'orcalink/server.py') return res.end('raise SystemExit("broken on purpose")\n')
  try {
    res.end(fs.readFileSync(path.join(root, f)))
  } catch {
    res.writeHead(404).end()
  }
})
await new Promise((r) => srv.listen(0, '127.0.0.1', r))
const base = `http://127.0.0.1:${srv.address().port}`
// The bundled copy: what build.sh puts in the extension's app/ folder.
const ext = fs.mkdtempSync(path.join(os.tmpdir(), 'orcalink-ext-'))
fs.mkdirSync(path.join(ext, 'server'))
fs.copyFileSync(launcher, path.join(ext, 'server', 'index.js'))
fs.cpSync(root, path.join(ext, 'app'), { recursive: true, filter: (p) => !p.includes('/.git') })
const bundled = path.join(ext, 'server', 'index.js')
const upd = { ORCALINK_PYTHON: process.env.PYTHON || 'python3', ORCALINK_GITHUB: base, ORCALINK_RAW: base }
const cache = path.join(tmp, '.config', 'orcaslicer-agentlink')
const status = async () => JSON.parse((await run(upd, bundled, 15000)).get(3).result.content[0].text)
check((await status()).commit === 'bundled', 'the first start serves the bundled copy at once')
for (let i = 0; i < 100 && !fs.existsSync(path.join(cache, 'app-' + head)); i++) await new Promise((r) => setTimeout(r, 200))
check((await status()).commit === head.slice(0, 7), 'the next start serves the version fetched in the background')
head = 'b'.repeat(40)
await status()
for (let i = 0; i < 100 && !JSON.parse(fs.readFileSync(path.join(cache, 'state.json'), 'utf8')).bad; i++) await new Promise((r) => setTimeout(r, 200))
check(JSON.parse(fs.readFileSync(path.join(cache, 'state.json'), 'utf8')).bad.includes(head), 'a commit that does not load is kept out')
check((await status()).commit === 'a'.repeat(7), 'the good version goes on serving')
// The pinned add-ons that FreeCAD Agent Link's launcher publishes into the
// app folder (addons/<repository>/<package>, with addons/.id), as for
// PrintLoop: orca_status lists them with no ORCALINK_ADDONS, and a newer
// commit fetched here keeps them.
const pkg = path.join(cache, 'app-' + 'a'.repeat(40), 'addons', 'ZZLoop-OrcaSlicer', 'zzloop')
fs.mkdirSync(pkg, { recursive: true })
fs.writeFileSync(path.join(pkg, '__init__.py'), '')
fs.writeFileSync(path.join(pkg, 'orcalink_addon.py'), 'VERSION = "0.1"\n\ndef tools(ctx):\n    return [{"name": "zzloop_score", "description": "Score.", "fn": lambda a: {"ok": True}}]\n')
fs.writeFileSync(path.join(cache, 'app-' + 'a'.repeat(40), 'addons', '.id'), 'a'.repeat(40) + '+ZZLoop-OrcaSlicer@' + '1'.repeat(40) + '\n')
const withAddon = await status()
check(withAddon.commit === 'a'.repeat(7) && (withAddon.addons || []).some((x) => x.module === 'zzloop.orcalink_addon' && x.tools.includes('zzloop_score')), 'orca_status lists the published add-on')
head = 'c'.repeat(40)
await status()
for (let i = 0; i < 100 && JSON.parse(fs.readFileSync(path.join(cache, 'state.json'), 'utf8')).current !== head; i++) await new Promise((r) => setTimeout(r, 200))
check(fs.existsSync(path.join(cache, 'app-' + head, 'addons', 'ZZLoop-OrcaSlicer', 'zzloop', 'orcalink_addon.py')), 'a newer commit fetched here keeps the published add-ons')
const after = await status()
check(after.commit === head.slice(0, 7) && (after.addons || []).some((x) => x.module === 'zzloop.orcalink_addon'), 'the newer commit lists them too')
srv.close()
console.log('launcher: serves the checkout over stdio, says what is missing without a Python, updates in the background and keeps a broken commit out, lists the published add-ons and keeps them on a newer commit')
