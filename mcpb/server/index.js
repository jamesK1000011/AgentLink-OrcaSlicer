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
  const text = (await get(`https://github.com/${OWNER}/${REPO}.git/info/refs?service=git-upload-pack`, 15000)).toString('utf8')
  const m = text.match(new RegExp(`([0-9a-f]{40}) refs/heads/${BRANCH}(\\n|\\0|$)`))
  if (!m) throw new Error('no head for ' + BRANCH)
  return m[1]
}

/** The app folder to serve from: a folder named by ORCALINK_FROM (a
 *  checkout, under test), the cached copy brought up to the branch's head,
 *  or the bundled copy. */
async function appDir() {
  if (process.env.ORCALINK_FROM) return { dir: expand(process.env.ORCALINK_FROM), version: 'local' }
  const dir = path.join(CACHE, 'app')
  const stateFile = path.join(CACHE, 'state.json')
  let state = {}
  try {
    state = JSON.parse(fs.readFileSync(stateFile, 'utf8'))
  } catch {}
  const cached = fs.existsSync(path.join(dir, 'orcalink_server.py')) ? { dir, version: state.version } : null
  if (String(process.env.ORCALINK_UPDATE) === 'false') return cached || { dir: BUNDLED, version: 'bundled' }
  try {
    const sha = await headSha()
    if (cached && state.version === sha) return cached
    const list = (await get(`https://raw.githubusercontent.com/${OWNER}/${REPO}/${sha}/FILES`)).toString('utf8')
    // The server's own files: not its tests, CI or this extension.
    const files = list.split('\n').map((x) => x.trim()).filter((x) => x && !x.startsWith('#') && !/^(tests|mcpb)\//.test(x))
    if (!files.includes('orcalink_server.py')) throw new Error('FILES names no orcalink_server.py')
    fs.mkdirSync(CACHE, { recursive: true })
    const stage = fs.mkdtempSync(path.join(CACHE, 'stage-'))
    try {
      for (let k = 0; k < files.length; k += 8) {
        await Promise.all(files.slice(k, k + 8).map(async (f) => {
          if (f.split('/').includes('..')) throw new Error(`bad path in FILES: ${f}`)
          const p = path.join(stage, f)
          fs.mkdirSync(path.dirname(p), { recursive: true })
          fs.writeFileSync(p, await get(`https://raw.githubusercontent.com/${OWNER}/${REPO}/${sha}/${f}`))
        }))
      }
      fs.rmSync(dir, { recursive: true, force: true })
      fs.renameSync(stage, dir)
    } catch (e) {
      fs.rmSync(stage, { recursive: true, force: true })
      throw e
    }
    fs.writeFileSync(stateFile, JSON.stringify({ version: sha, at: new Date().toISOString() }))
    log(`fetched ${REPO} ${sha.slice(0, 7)}`)
    return { dir, version: sha }
  } catch (e) {
    log('no update from GitHub:', e.message)
    return cached || { dir: BUNDLED, version: 'bundled' }
  }
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
  const app = await appDir()
  fs.mkdirSync(OUT, { recursive: true })
  log(`serving ${app.version} from ${app.dir} with ${py}`)
  const child = spawn(py, [path.join(app.dir, 'orcalink_server.py'), '--out', OUT], {
    stdio: ['inherit', 'inherit', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', ORCALINK_VERSION: String(app.version || '') },
  })
  child.stderr.on('data', (d) => logFile.write(d))
  child.on('exit', (code, sig) => {
    log(`server ended (${code ?? sig})`)
    process.exit(code ?? 1)
  })
  for (const s of ['SIGTERM', 'SIGINT']) process.on(s, () => child.kill(s))
}

main().catch((e) => {
  log('failed:', e.stack || e.message)
  serveError(`OrcaSlicer Agent Link could not start: ${e.message}`)
})
