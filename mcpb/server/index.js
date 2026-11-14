#!/usr/bin/env node
// SPDX-License-Identifier: LGPL-2.1-or-later
// OrcaSlicer Agent Link as a Claude Desktop extension: the MCP server Claude
// starts. It brings Agent Link for OrcaSlicer up to date from GitHub (the
// copy bundled with the extension when GitHub cannot be reached), finds a
// Python 3.9 or newer already on this Mac, and runs orcalink_server.py over
// stdio. No network port is opened: Claude and the server talk only through
// the pipes Claude made.

'use strict'
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawn, spawnSync } = require('child_process')

const HOME = os.homedir()
const OWNER = 'jamesK1000011'
const REPO = 'OrcaSlicer-AgentLink'
const BRANCH = 'main'
// Where the repository is read from (a local server stands in under test).
const GH = process.env.ORCALINK_GITHUB || 'https://github.com'
const RAW = process.env.ORCALINK_RAW || 'https://raw.githubusercontent.com'
const HERE = path.dirname(__dirname)
const BUNDLED = path.join(HERE, 'app')
const CACHE = expand(process.env.ORCALINK_CACHE || path.join(HOME, '.config', 'orcaslicer-agentlink'))
const OUT = expand(process.env.AGENTLINK_OUT || path.join(HOME, 'AgentLink'))
const LOG_DIR = expand(process.env.ORCALINK_LOG_DIR || path.join(HOME, 'Library', 'Logs', 'OrcaSlicer Agent Link'))

fs.mkdirSync(LOG_DIR, { recursive: true })
const logFile = fs.createWriteStream(path.join(LOG_DIR, 'launcher.log'), { flags: 'a' })
function log(...a) {
  logFile.write(`[${new Date().toISOString()}] ${a.join(' ')}\n`)
}

function expand(p) {
  return String(p).replace(/^~(?=$|\/)/, HOME).replace(/\$\{HOME\}/g, HOME)
}

async function get(url, timeout = 30000) {
  const r = await fetch(url, { headers: { 'User-Agent': 'orcaslicer-agentlink' }, signal: AbortSignal.timeout(timeout) })
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  return Buffer.from(await r.arrayBuffer())
}

/** The branch's head from git's own ref list (not held to the API's 60
 *  calls an hour). */
async function headSha() {
  const text = (await get(`${GH}/${OWNER}/${REPO}.git/info/refs?service=git-upload-pack`, 15000)).toString('utf8')
  const m = text.match(new RegExp(`([0-9a-f]{40}) refs/heads/${BRANCH}(\\n|\\0|$)`))
  if (!m) throw new Error('no head for ' + BRANCH)
  return m[1]
}

const STATE = path.join(CACHE, 'state.json')
function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE, 'utf8'))
  } catch {
    return {}
  }
}
function writeState(st) {
  fs.mkdirSync(CACHE, { recursive: true })
  const tmp = STATE + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(st))
  fs.renameSync(tmp, STATE)
}
const versionDir = (sha) => path.join(CACHE, `app-${sha}`)

/** The app folder to serve from, at once (no network before Claude gets
 *  its answer): a folder named by ORCALINK_FROM (a checkout, under test),
 *  the version fetched last time, or the bundled copy. */
function appDir() {
  if (process.env.ORCALINK_FROM) return { dir: expand(process.env.ORCALINK_FROM), version: 'local' }
  const st = readState()
  if (st.current && fs.existsSync(path.join(versionDir(st.current), 'orcalink_server.py'))) return { dir: versionDir(st.current), version: st.current }
  return { dir: BUNDLED, version: 'bundled' }
}

/** In the background, after serving has started: the branch's newest
 *  commit fetched into a folder of its own, checked (it must import), then
 *  made the version the next start serves. A running server's folder is
 *  never touched; the version before is kept to fall back to. */
async function updateInBackground(py) {
  if (process.env.ORCALINK_FROM || String(process.env.ORCALINK_UPDATE) === 'false') return
  const st = readState()
  const sha = await headSha()
  if (sha === st.current || (st.bad || []).includes(sha)) return
  const list = (await get(`${RAW}/${OWNER}/${REPO}/${sha}/FILES`)).toString('utf8')
  // The server's own files: not its tests, CI or this extension.
  const files = list.split('\n').map((x) => x.trim()).filter((x) => x && !x.startsWith('#') && !/^(tests|mcpb)\//.test(x))
  if (!files.includes('orcalink_server.py')) throw new Error('FILES names no orcalink_server.py')
  fs.mkdirSync(CACHE, { recursive: true })
  const stage = fs.mkdtempSync(path.join(CACHE, 'stage-'))
  try {
    for (let k = 0; k < files.length; k += 8) {
      await Promise.all(files.slice(k, k + 8).map(async (f) => {
        if (f.split('/').includes('..') || path.isAbsolute(f)) throw new Error(`bad path in FILES: ${f}`)
        const p = path.join(stage, f)
        fs.mkdirSync(path.dirname(p), { recursive: true })
        fs.writeFileSync(p, await get(`${RAW}/${OWNER}/${REPO}/${sha}/${f}`))
      }))
    }
    // It must at least import and build its tools before it is used.
    const chk = spawnSync(py, ['-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from orcalink.server import build; build(sys.argv[2])', stage, fs.mkdtempSync(path.join(os.tmpdir(), 'orcalink-check-'))], { encoding: 'utf8', timeout: 60000 })
    if (chk.status !== 0) {
      writeState({ ...readState(), bad: [...(readState().bad || []), sha].slice(-5) })
      throw new Error(`${sha.slice(0, 7)} did not load, kept out: ${(chk.stderr || '').slice(-300)}`)
    }
    fs.rmSync(versionDir(sha), { recursive: true, force: true })
    fs.renameSync(stage, versionDir(sha))
  } catch (e) {
    fs.rmSync(stage, { recursive: true, force: true })
    throw e
  }
  const now = readState()
  writeState({ ...now, current: sha, previous: now.current || null, at: new Date().toISOString() })
  // Older versions go; the one before stays to fall back to.
  for (const n of fs.readdirSync(CACHE)) {
    const v = n.startsWith('app-') ? n.slice(4) : null
    if (v && v !== sha && v !== now.current) fs.rmSync(path.join(CACHE, n), { recursive: true, force: true })
  }
  log(`fetched ${REPO} ${sha.slice(0, 7)}: served from the next start`)
}

/** A version that dies straight away is kept out, and the one before it
 *  serves from the next start. */
function markBad(version) {
  const st = readState()
  if (!version || version !== st.current) return
  writeState({ ...st, current: st.previous || null, previous: null, bad: [...(st.bad || []), version].slice(-5) })
  log(`${version.slice(0, 7)} ended at once: the version before it serves from the next start`)
}

/** A Python 3.9+ that is already here. /usr/bin/python3 only when the
 *  Xcode command line tools are installed: without them it opens macOS's
 *  install dialog instead of running. */
function findPython() {
  // One named (ORCALINK_PYTHON) is the only one tried.
  const cands = process.env.ORCALINK_PYTHON ? [expand(process.env.ORCALINK_PYTHON)] : []
  if (!cands.length) cands.push('/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/Library/Frameworks/Python.framework/Versions/Current/bin/python3')
  if (!process.env.ORCALINK_PYTHON && spawnSync('/usr/bin/xcode-select', ['-p'], { encoding: 'utf8' }).status === 0) cands.push('/usr/bin/python3')
  for (const root of process.env.ORCALINK_PYTHON ? [] : ['/Applications', path.join(HOME, 'Applications')]) {
    try {
      for (const n of fs.readdirSync(root).filter((x) => /^FreeCAD.*\.app$/.test(x)).sort().reverse()) {
        cands.push(path.join(root, n, 'Contents', 'Resources', 'bin', 'python'))
      }
    } catch {}
  }
  if (process.platform !== 'darwin' && !process.env.ORCALINK_PYTHON) cands.push('python3')
  for (const c of cands) {
    if (c.includes('/') && !fs.existsSync(c)) continue
    const r = spawnSync(c, ['-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], { encoding: 'utf8', timeout: 20000 })
    const v = (r.stdout || '').trim().split('.').map(Number)
    if (r.status === 0 && (v[0] > 3 || (v[0] === 3 && v[1] >= 9))) return c
  }
  return null
}

/** With nothing to run, Claude still gets an answer that says why. */
function serveError(text) {
  const rl = require('readline').createInterface({ input: process.stdin })
  rl.on('line', (line) => {
    let m
    try {
      m = JSON.parse(line)
    } catch {
      return
    }
    if (m.id === undefined) return
    let result
    if (m.method === 'initialize') result = { protocolVersion: (m.params && m.params.protocolVersion) || '2025-06-18', capabilities: { tools: {} }, serverInfo: { name: 'orcaslicer-agentlink', version: '0' }, instructions: text }
    else if (m.method === 'tools/list') result = { tools: [] }
    else result = { content: [{ type: 'text', text }], isError: true }
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result }) + '\n')
  })
}

async function main() {
  log(`start: node ${process.version}`)
  const py = findPython()
  if (!py) {
    log('no Python 3.9 or newer found')
    serveError('OrcaSlicer Agent Link needs a Python 3.9 or newer on this Mac (Homebrew, python.org, the Xcode command line tools, or FreeCAD installed in /Applications).')
    return
  }
  const app = appDir()
  fs.mkdirSync(OUT, { recursive: true })
  log(`serving ${app.version} from ${app.dir} with ${py}`)
  const started = Date.now()
  // -I: none of the person's PYTHONPATH or startup files in the server.
  const child = spawn(py, ['-I', path.join(app.dir, 'orcalink_server.py'), '--out', OUT], {
    stdio: ['inherit', 'inherit', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', ORCALINK_VERSION: String(app.version || '') },
  })
  child.stderr.on('data', (d) => logFile.write(d))
  child.on('exit', (code, sig) => {
    log(`server ended (${code ?? sig})`)
    if (code && Date.now() - started < 10000) markBad(app.version)
    process.exit(code ?? 1)
  })
  updateInBackground(py).catch((e) => log('no update from GitHub:', e.message))
  for (const s of ['SIGTERM', 'SIGINT']) process.on(s, () => child.kill(s))
}

main().catch((e) => {
  log('failed:', e.stack || e.message)
  serveError(`OrcaSlicer Agent Link could not start: ${e.message}`)
})
