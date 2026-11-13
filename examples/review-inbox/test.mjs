import assert from 'node:assert/strict';
import {prs,ranked,requiredChecks} from './model.mjs';
assert.equal(prs.length,100);
assert.equal(new Set(prs.map(p=>p.id)).size,100);
assert.equal(prs.filter(p=>p.waiting).length,18);
assert.equal(ranked(prs,{}).length,82);
assert.equal(ranked(prs,{}).slice(5).length,77);
assert.equal(ranked(prs,{})[0].id,184);
assert.equal(ranked(prs,{security:true})[0].id,187);
assert.equal(ranked(prs,{reliability:true})[0].id,163);
assert.equal(ranked(prs,{},new Set([184]))[0].id,172);
assert.equal(requiredChecks(prs[0],{}).find(c=>c.name==='Sun PR review').status,'Outdated');
assert.equal(requiredChecks(prs[4],{security:true}).find(c=>c.name==='Security review').status,'Not run');
assert.equal(requiredChecks(prs[0],{ponytail:true}).find(c=>c.name==='Ponytail').status,'Not run');
assert.equal(prs[0].review,'Outdated');
assert.equal(requiredChecks(prs[3],{reliability:true}).find(c=>c.name==='Reliability').status,'Not run');
assert.match(requiredChecks(prs[1],{}).find(c=>c.name==='Sun PR review').detail,/No review recorded/);
assert.match(requiredChecks(prs.find(p=>p.tests==='Not run'),{})[0].detail,/No run recorded/);
console.log('16 assertions passed: counts, ranking, personalization, completion, and check provenance.');

const {settingsKey,readSettings,reviewAction,githubReviewUrl} = await import('./review-action.mjs');
const prUrl = 'https://github.com/example/project/pull/12';
assert.equal(githubReviewUrl(prUrl), prUrl+'/files');
assert.equal(githubReviewUrl(prUrl+'/files?ignored=1#review'), prUrl+'/files');
for(const url of ['javascript:alert(1)','http://github.com/example/project/pull/12',
  'https://github.com.evil.test/example/project/pull/12','https://user:pass@github.com/example/project/pull/12',
  'https://github.com/example/project/issues/12','https://github.com/example/project/pull/0',
  'https://github.com:444/example/project/pull/12',null,{}]) assert.equal(githubReviewUrl(url),null);
assert.deepEqual(readSettings(null),{action:'local',links:{}});
assert.deepEqual(readSettings({getItem(){throw Error('blocked')}}),{action:'local',links:{}});
assert.deepEqual(readSettings({getItem:()=>'{broken'}),{action:'local',links:{}});
const settings=readSettings({getItem:key=>{assert.equal(key,settingsKey);return JSON.stringify({action:'github',links:{184:prUrl,172:'javascript:alert(1)'}})}});
assert.deepEqual(settings,{action:'github',links:{184:prUrl+'/files'}});
assert.deepEqual(reviewAction(settings,184),{label:'Review on GitHub',url:prUrl+'/files',local:false});
assert.deepEqual(reviewAction(settings,172),{label:'Link GitHub PR',url:null,local:false});
assert.deepEqual(reviewAction({action:'local',links:settings.links},184),{label:'Mark reviewed',url:null,local:true});
assert.equal(readSettings({getItem:()=>JSON.stringify({action:'approve'})}).action,'local');
console.log('Review-action tests passed: URL validation, persistence recovery, explicit linking, and local default.');
