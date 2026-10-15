import { readFile, readdir, rm } from 'node:fs/promises';
import { resolve, sep } from 'node:path';

const staticDir = resolve(process.cwd(), '../app/dist/static');
const bundlePattern = /^index-[\w-]+\.(?:js|css)$/;

async function cleanOldBundles() {
  let entries = [];
  try {
    entries = await readdir(staticDir, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') {
      return;
    }
    throw error;
  }

  const emitted = new Set();
  try {
    const manifest = JSON.parse(await readFile(resolve(staticDir, '../.vite/manifest.json'), 'utf8'));
    for (const chunk of Object.values(manifest)) {
      for (const file of [chunk.file, ...(chunk.css || [])]) {
        if (typeof file !== 'string' || !/\.(?:js|css)$/.test(file)) continue;
        const target = resolve(staticDir, '..', file);
        if (target.startsWith(staticDir + sep)) emitted.add(target);
      }
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  for (const entry of entries) {
    if (entry.isFile() && bundlePattern.test(entry.name)) emitted.add(resolve(staticDir, entry.name));
  }
  await Promise.all(
    [...emitted].map(target => rm(target, { force: true })),
  );
}

await cleanOldBundles();
