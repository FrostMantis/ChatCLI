#!/usr/bin/env node
/**
 * Copies the livekit-client browser build into src/renderer/vendor/ so the
 * renderer can load it from its own origin.
 *
 * The renderer's CSP allows scripts from 'self' only, which is deliberate: the
 * app must not execute code fetched from a CDN at runtime (see UI-CONTRACT
 * §10.4). livekit-client is already a declared dependency, so this only moves
 * the prebuilt UMD bundle to where a same-origin <script> tag can reach it.
 *
 * Run after `npm install`, and again whenever the dependency is upgraded:
 *
 *   node scripts/vendor-livekit.mjs
 */

import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtempSync, mkdirSync, copyFileSync, existsSync, readFileSync, rmSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, 'src', 'renderer', 'vendor');
const outFile = join(outDir, 'livekit-client.umd.js');

/** The path of the UMD bundle inside the published package. */
const BUNDLE = join('dist', 'livekit-client.umd.js');

const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const range = pkg.dependencies?.['livekit-client'];
if (!range) {
  console.error('livekit-client is not listed in package.json dependencies.');
  process.exit(1);
}

/** Resolve the installed copy, if `npm install` has already been run. */
function fromNodeModules() {
  const require = createRequire(join(root, 'package.json'));
  try {
    const manifest = require.resolve('livekit-client/package.json');
    const candidate = join(dirname(manifest), BUNDLE);
    return existsSync(candidate) ? candidate : null;
  } catch {
    return null;
  }
}

/**
 * Fall back to downloading just the tarball. `npm pack` fetches the single
 * package rather than installing the whole dependency tree, which keeps this
 * usable on a machine that has not run `npm install`.
 */
function fromRegistry() {
  const spec = `livekit-client@${range}`;
  const work = mkdtempSync(join(tmpdir(), 'livekit-vendor-'));
  console.log(`No installed copy found — fetching ${spec} from the registry…`);
  try {
    const tarball = execFileSync('npm', ['pack', spec, '--silent', '--pack-destination', work], {
      cwd: root,
      encoding: 'utf8',
    }).trim().split('\n').pop();

    execFileSync('tar', ['-xzf', join(work, tarball), '-C', work, join('package', BUNDLE)]);

    const extracted = join(work, 'package', BUNDLE);
    if (!existsSync(extracted)) throw new Error(`${BUNDLE} is not present in ${tarball}`);

    mkdirSync(outDir, { recursive: true });
    copyFileSync(extracted, outFile);
    return outFile;
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

const installed = fromNodeModules();
if (installed) {
  mkdirSync(outDir, { recursive: true });
  copyFileSync(installed, outFile);
  console.log(`Copied from node_modules: ${installed}`);
} else {
  fromRegistry();
}

const kb = (statSync(outFile).size / 1024).toFixed(0);
console.log(`Wrote src/renderer/vendor/livekit-client.umd.js (${kb} KB)`);
console.log('The renderer loads it via a <script> tag in pages/index.html; window.LiveKit is then defined.');
