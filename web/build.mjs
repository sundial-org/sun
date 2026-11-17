import { build } from 'esbuild';
import { gzipSync } from 'node:zlib';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
const result = await build({entryPoints:['app.js'], bundle:true, minify:true, format:'esm', target:'es2022', write:false, legalComments:'inline'});
writeFileSync('../sun/review_assets/app.js.gz', gzipSync(result.outputFiles[0].contents, {level:9}));
writeFileSync('../sun/review_assets/PIERRE-LICENSE.txt', readFileSync('node_modules/@pierre/diffs/LICENSE.md'));
console.log(`Bundled ${(result.outputFiles[0].contents.length/1024/1024).toFixed(1)} MB (served locally, gzip compressed)`);

const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const notices = [];
for (const [path, info] of Object.entries(lock.packages)) {
  if (!path || info.dev) continue;
  for (const file of readdirSync(path).filter(name => /^(license|notice|copying)(\.|$)/i.test(name))) {
    notices.push(`${path} @ ${info.version} / ${file}\n\n${readFileSync(`${path}/${file}`, 'utf8')}`);
  }
}
const renderer = 'node_modules/@aiden0z/pptx-renderer';
const embeddedNotices = ['THIRD_PARTY_NOTICES.md', ...readdirSync(`${renderer}/licenses`).map(f => `licenses/${f}`)];
for (const file of embeddedNotices) notices.push(`${renderer}/${file}\n\n${readFileSync(`${renderer}/${file}`, 'utf8')}`);
writeFileSync('../sun/review_assets/THIRD-PARTY-NOTICES.txt', notices.join('\n\n' + '='.repeat(72) + '\n\n').replace(/\r\n/g, '\n'));
