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

function run(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [launcher], { env: { ...process.env, HOME: tmp, ORCALINK_LOG_DIR: path.join(tmp, 'logs'), AGENTLINK_OUT: path.join(tmp, 'out'), ...env }, stdio: ['pipe', 'pipe', 'pipe'] })
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
          child.kill()
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
console.log('launcher: serves the checkout over stdio, and says what is missing without a Python')
