import { build } from 'esbuild';
import { gzipSync } from 'node:zlib';
import { readFileSync, writeFileSync } from 'node:fs';
const result = await build({entryPoints:['app.js'], bundle:true, minify:true, format:'esm', target:'es2022', write:false, legalComments:'inline'});
writeFileSync('../sun/review_assets/app.js.gz', gzipSync(result.outputFiles[0].contents, {level:9}));
writeFileSync('../sun/review_assets/PIERRE-LICENSE.txt', readFileSync('node_modules/@pierre/diffs/LICENSE.md'));
console.log(`Bundled ${(result.outputFiles[0].contents.length/1024/1024).toFixed(1)} MB (served locally, gzip compressed)`);
