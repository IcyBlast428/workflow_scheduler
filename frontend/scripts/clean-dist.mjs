import { readdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

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

  await Promise.all(
    entries
      .filter((entry) => entry.isFile() && bundlePattern.test(entry.name))
      .map((entry) => rm(resolve(staticDir, entry.name), { force: true })),
  );
}

await cleanOldBundles();
